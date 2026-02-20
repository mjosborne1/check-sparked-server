import os
import sys
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from collections import defaultdict
from contextlib import redirect_stdout
from io import StringIO

# Load environment variables from .env file
load_dotenv()

# 1. Configuration
# Change this to your specific Sparked environment URL
BASE_URL = os.getenv("FHIR_SERVER", "https://smile.sparked-fhir.com/ereq")
USE_AUTH = os.getenv("USE_AUTH", "false").lower() == "true"
FHIR_USERNAME = os.getenv("FHIR_USERNAME", "")
FHIR_PASSWORD = os.getenv("FHIR_PASSWORD", "")

# GitHub test data repository
GITHUB_REPO = "hl7au/au-fhir-test-data"
GITHUB_API_BASE = "https://api.github.com"
TEST_DATA_PATH = "au-fhir-test-data-set"

# Get test data filters from environment variable
TEST_DATA_FILTERS_ENV = os.getenv("TEST_DATA_FILTERS", "au-core,au-erequesting")
TEST_DATA_FILTERS = [f.strip() for f in TEST_DATA_FILTERS_ENV.split(",") if f.strip()]

# GitHub token for higher rate limit (optional)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Output file path configuration
OUTPUT_FILE_PATH = os.path.expandvars(os.getenv("OUTPUT_FILE_PATH", "$HOME/data/check-sparked-server"))
OUTPUT_FILE_PATH = os.path.expanduser(OUTPUT_FILE_PATH)

PROFILES_TO_CHECK = {
    "Patient": "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-patient",
    "ServiceRequest": "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-servicerequest-imag"
}

# Resource types to check for instance data
RESOURCE_TYPES_TO_CHECK = [
    "Patient", "Practitioner", "PractitionerRole", "Organization", 
    "HealthcareService", "Location", "ServiceRequest", "RelatedPerson",
    "Observation", "DocumentReference", "Task", "CommunicationRequest"
]

def check_versions():
    print(f"--- Auditing Sparked Servers: {BASE_URL} ---")
    if USE_AUTH:
        print(f"    Using Basic Authentication (User: {FHIR_USERNAME})\n")
    else:
        print("    No authentication configured\n")
    
    for name, url in PROFILES_TO_CHECK.items():
        # Querying the StructureDefinition by its canonical URL
        search_url = f"{BASE_URL}/StructureDefinition?url={url}"
        
        try:
            # Prepare authentication if enabled
            auth = HTTPBasicAuth(FHIR_USERNAME, FHIR_PASSWORD) if USE_AUTH else None
            
            response = requests.get(
                search_url, 
                headers={"Accept": "application/fhir+json"},
                auth=auth
            )
            response.raise_for_status()
            bundle = response.json()
            
            if bundle.get("total", 0) == 0:
                print(f"[!] {name}: Profile not found on server.")
                continue
            
            # Simple FHIRPath-like extraction using Python list comprehension
            # Grabs versions from all entries in the bundle
            versions = [entry['resource'].get('version') for entry in bundle.get('entry', [])]
            
            # Identify the 'active' version
            active_versions = [
                entry['resource']['version'] 
                for entry in bundle.get('entry', []) 
                if entry['resource'].get('status') == 'active'
            ]

            print(f"[*] {name}:")
            print(f"    - All Found Versions: {', '.join(versions)}")
            print(f"    - Currently Active:   {active_versions[0] if active_versions else 'NONE'}")
            
            # Version Logic Check
            if "1.0.0" in str(active_versions):
                print(f"    ✅ VERIFIED: Server is updated to 1.0.0 artifacts.")
            else:
                print(f"    ⚠️ WARNING: Server  is not serving 1.0.0 ")
                
        except Exception as e:
            print(f"[X] Error checking {name}: {e}")
        print("-" * 40)


def get_server_resource_summary():
    """Get summary of instance data on the server"""
    print("\n=== Server Instance Data Summary ===\n")
    
    auth = HTTPBasicAuth(FHIR_USERNAME, FHIR_PASSWORD) if USE_AUTH else None
    resource_counts = {}
    
    for resource_type in RESOURCE_TYPES_TO_CHECK:
        try:
            # Get count using _summary=count
            search_url = f"{BASE_URL}/{resource_type}?_summary=count"
            response = requests.get(
                search_url,
                headers={"Accept": "application/fhir+json"},
                auth=auth,
                timeout=10
            )
            
            if response.status_code == 200:
                bundle = response.json()
                count = bundle.get("total", 0)
                resource_counts[resource_type] = count
                if count > 0:
                    print(f"[*] {resource_type}: {count} instances")
            elif response.status_code == 404:
                # Resource type not supported on server
                resource_counts[resource_type] = None
            else:
                print(f"[!] {resource_type}: Unable to query (HTTP {response.status_code})")
                resource_counts[resource_type] = None
                
        except Exception as e:
            print(f"[X] Error checking {resource_type}: {e}")
            resource_counts[resource_type] = None
    
    return resource_counts


def get_github_test_data_summary():
    """Get summary of test data available in GitHub repository"""
    print("\n=== GitHub Test Data Repository Summary ===\n")
    
    test_data_files = defaultdict(list)
    
    # Setup headers with authentication if token provided
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
        print("[INFO] Using GitHub token for authentication\n")
    
    try:
        # Fetch the contents of the test data directory
        api_url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{TEST_DATA_PATH}"
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        contents = response.json()
        
        # Find subdirectories that match our filters
        filtered_dirs = []
        for item in contents:
            if item['type'] == 'dir':
                dir_name = item['name']
                # Check if directory name starts with any of our filters
                for filter_prefix in TEST_DATA_FILTERS:
                    if dir_name.startswith(filter_prefix):
                        filtered_dirs.append(item)
                        break
        
        print(f"Repository: https://github.com/{GITHUB_REPO}")
        print(f"Test Data Path: {TEST_DATA_PATH}")
        print(f"Filters: {', '.join(TEST_DATA_FILTERS)}")
        print(f"Found {len(filtered_dirs)} filtered directories: {', '.join([d['name'] for d in filtered_dirs])}")
        print(f"Note: GitHub API limits directory listings to 1000 items per request\n")
        
        # Process each filtered directory
        for directory in filtered_dirs:
            dir_name = directory['name']
            dir_url = directory['url']
            
            try:
                # GitHub API returns all directory contents in one call (up to 1000 items)
                dir_response = requests.get(dir_url, headers=headers, timeout=10)
                dir_response.raise_for_status()
                dir_contents = dir_response.json()
                
                total_files_in_dir = 0
                
                # Process files in this directory
                unmatched_files = []
                for item in dir_contents:
                    if item.get('type') == 'file' and item.get('name', '').endswith('.json'):
                        filename = item['name']
                        total_files_in_dir += 1
                        # Try to match resource type from filename
                        matched = False
                        for resource_type in RESOURCE_TYPES_TO_CHECK:
                            if filename.startswith(resource_type):
                                test_data_files[resource_type].append(f"{dir_name}/{filename}")
                                matched = True
                                break
                        if not matched:
                            unmatched_files.append(filename)
                
                print(f"[DEBUG] {dir_name}: Found {total_files_in_dir} JSON files")
                
                # Check specifically for PractitionerRole files
                practitioner_role_files = [f for f in unmatched_files if f.startswith("PractitionerRole")]
                if practitioner_role_files:
                    print(f"[DEBUG]   Found {len(practitioner_role_files)} PractitionerRole files in unmatched (BUG!)")
                    print(f"[DEBUG]   Examples: {practitioner_role_files[:3]}")
                
                if unmatched_files:
                    print(f"[DEBUG]   Total unmatched files: {len(unmatched_files)} (e.g., {unmatched_files[0]}, {unmatched_files[1] if len(unmatched_files) > 1 else ''})")
            except Exception as e:
                print(f"[!] Error fetching {dir_name}: {str(e)[:100]}")
        
        # Display summary by resource type
        print()
        for resource_type in sorted(test_data_files.keys()):
            count = len(test_data_files[resource_type])
            print(f"[*] {resource_type}: {count} test files")
        
        if not test_data_files:
            print("[!] No test data files found matching expected resource types")
            
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403 and 'rate limit' in str(e).lower():
            print(f"[X] GitHub API rate limit exceeded!")
            print(f"[!] Without token: 60 requests/hour")
            print(f"[!] With token: 5000 requests/hour")
            print(f"[!] Add GITHUB_TOKEN to .env file")
            print(f"[!] Create token at: https://github.com/settings/tokens")
        else:
            print(f"[X] Error fetching GitHub test data: {e}")
        if not test_data_files:
            print("[!] No test data files found matching expected resource types")
            
    except Exception as e:
        print(f"[X] Error fetching GitHub test data: {e}")
    
    # Handle GitHub API 1000-item limit for resource types not found
    # Use search API for any missing resource types
    missing_types = [rt for rt in RESOURCE_TYPES_TO_CHECK if rt not in test_data_files]
    if missing_types:
        print(f"[DEBUG] Resource types missing from directory listing (API limit?): {', '.join(missing_types)}")
        print(f"[DEBUG] Attempting search API for missing types...")
        
        for resource_type in missing_types:
            try:
                # Use GitHub search API to find files matching the resource type
                search_url = "https://api.github.com/search/code"
                total_found = 0
                page = 1
                
                while page <= 10:  # Limit to 10 pages (1000 results max per GitHub search API)
                    search_params = {
                        "q": f"repo:{GITHUB_REPO} path:{TEST_DATA_PATH} filename:{resource_type}-",
                        "per_page": 100,
                        "page": page
                    }
                    
                    search_response = requests.get(search_url, headers=headers, params=search_params, timeout=10)
                    
                    if search_response.status_code == 200:
                        search_results = search_response.json()
                        items = search_results.get('items', [])
                        
                        if not items:
                            break  # No more results
                        
                        # Extract filenames from search results
                        for item in items:
                            path = item.get('path', '')
                            if f"/{resource_type}-" in path:
                                test_data_files[resource_type].append(path)
                                total_found += 1
                        
                        # Check if we got all results
                        total_count = search_results.get('total_count', 0)
                        if total_found >= total_count or len(items) < 100:
                            break
                        
                        page += 1
                    else:
                        break
                
                if total_found > 0:
                    print(f"[DEBUG] Found {total_found} {resource_type} files via search API")
            except Exception as e:
                print(f"[DEBUG] Search API failed for {resource_type}: {str(e)[:50]}")
        
    return test_data_files


def compare_server_to_github(server_counts, github_files):
    """Compare server instance data to GitHub test data"""
    print("\n=== Comparison: Server vs GitHub Test Data ===\n")
    
    all_resource_types = set(server_counts.keys()) | set(github_files.keys())
    
    for resource_type in sorted(all_resource_types):
        server_count = server_counts.get(resource_type, 0)
        github_count = len(github_files.get(resource_type, []))
        
        # Skip if resource type not found in either
        if server_count is None and github_count == 0:
            continue
        
        status = ""
        if server_count is None:
            status = "❓ Not available on server"
        elif server_count == 0 and github_count > 0:
            status = "⚠️  Missing - GitHub has test data but server has none"
        elif server_count > 0 and github_count == 0:
            status = "⚠️  Server has data but no GitHub test files (missing test data reference)"
        elif server_count == github_count:
            status = f"✅ Perfect match ({server_count} instances)"
        elif server_count > github_count:
            status = f"⚠️  ERROR: Server has more instances than test data ({server_count} vs {github_count})"
        else:
            status = f"⚠️  Server has fewer instances ({server_count} vs {github_count})"
        
        print(f"[*] {resource_type}: {status}")
    
    print("\n" + "=" * 60)
    print("Note: This comparison shows whether test data exists, not if")
    print("the specific instances match. Use the GitHub test data to")
    print("validate server conformance: https://github.com/hl7au/au-fhir-test-data")
    print("=" * 60)


def check_instance_data():
    """Main function to check and compare instance data"""
    server_counts = get_server_resource_summary()
    github_files = get_github_test_data_summary()
    compare_server_to_github(server_counts, github_files)


def write_output_to_file(output_content, file_path):
    """Write output to a file, ensuring directory exists"""
    try:
        # Create directory if it doesn't exist
        directory = Path(file_path).parent
        directory.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"check_results_{timestamp}.txt"
        full_path = directory / filename
        
        # Write to file
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(output_content)
        
        print(f"\n✅ Results saved to: {full_path}")
        return str(full_path)
    except Exception as e:
        print(f"\n❌ Error writing to file: {e}")
        return None


if __name__ == "__main__":
    # Capture output for file writing
    output_buffer = StringIO()
    
    # Use a custom writer that writes to both console and buffer
    class TeeWriter:
        def __init__(self, *writers):
            self.writers = writers
        
        def write(self, text):
            for writer in self.writers:
                writer.write(text)
        
        def flush(self):
            for writer in self.writers:
                writer.flush()
    
    # Redirect stdout to write to both console and buffer
    original_stdout = sys.stdout
    sys.stdout = TeeWriter(original_stdout, output_buffer)
    
    try:
        check_versions()
        print("\n")
        check_instance_data()
    finally:
        # Restore original stdout
        sys.stdout = original_stdout
    
    # Write captured output to file
    output_content = output_buffer.getvalue()
    write_output_to_file(output_content, OUTPUT_FILE_PATH)

import os
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

# Load environment variables from .env file
load_dotenv()

# 1. Configuration
# Change this to your specific Sparked environment URL
BASE_URL = os.getenv("FHIR_SERVER", "https://smile.sparked-fhir.com/ereq")
USE_AUTH = os.getenv("USE_AUTH", "false").lower() == "true"
FHIR_USERNAME = os.getenv("FHIR_USERNAME", "")
FHIR_PASSWORD = os.getenv("FHIR_PASSWORD", "")

PROFILES_TO_CHECK = {
    "Patient": "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-patient",
    "ServiceRequest": "http://hl7.org.au/fhir/ereq/StructureDefinition/au-erequesting-servicerequest-imag"
}

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

if __name__ == "__main__":
    check_versions()

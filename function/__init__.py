from azure.core.pipeline import Pipeline
from azure.core.pipeline.transport import HttpRequest, HttpResponse
from azure.core.pipeline.policies import BearerTokenCredentialPolicy, HttpLoggingPolicy, RedirectPolicy  
from azure.core.pipeline.transport import RequestsTransport
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
import logging
from dotenv import load_dotenv
from msal import ConfidentialClientApplication, PublicClientApplication
import os

load_dotenv()

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("msal").setLevel(logging.WARN)
print(os.getenv("CLIENT_ID"))
app = PublicClientApplication(
    os.getenv("CLIENT_ID"),
    authority="https://login.microsoftonline.com/d05bc194-94bf-4ad6-ae2e-1db0f2e38f5e")

result = None

accounts = app.get_accounts()
if accounts:
    # If so, you could then somehow display these accounts and let end user choose
    print("Pick the account you want to use to proceed:")
    for a in accounts:
        print(a["username"])
    # Assuming the end user chose this one
    chosen = accounts[0]
    # Now let's try to find a token in cache for this account
    result = app.acquire_token_silent(["User.Read"], account=chosen)

if not result:
    # So no suitable token exists in cache. Let's get a new one from Azure AD.
    # result = app.acquire_token_interactive(["User.Read"], login_hint=os.getenv("USERNAME"))
    result = app.acquire_token_by_authorization_code(..., scopes=["https://graph.microsoft.com/.default"])
if "access_token" in result:
    print(result["access_token"])  # Yay!
else:
    print(result.get("error"))
    print(result.get("error_description"))
    print(result.get("correlation_id"))  # You may need this when reporting a bug
# credential = DefaultAzureCredential()
# credential_policy = BearerTokenCredentialPolicy(credential, 'https://graph.microsoft.com/.default')

# policies = [
#     UserAgentPolicy("SSCPlusDrupal"),  
#     NetworkTraceLoggingPolicy(), 
#     credential_policy,
#     HttpLoggingPolicy(),
#     RedirectPolicy()
# ]

# transport = RequestsTransport(connection_verify=False)
# pipeline = Pipeline(transport=transport, policies=policies) 
# request = HttpRequest('GET', 'https://plus-dev.ssc-spc.gc.ca/rest/all-ids')
# response = pipeline.run(request)

# # Get the response  
# print("RESPONSE HTTP CODE: " + str(response.http_response.status_code)) 
# print("RESPONSE BODY: " + str(response.http_response.headers))
# print(response.http_response.text())
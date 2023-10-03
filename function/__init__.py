from azure.core.pipeline import Pipeline
import pip_system_certs.wrapt_requests
from azure.core.pipeline.transport import HttpRequest, HttpResponse
from azure.core.pipeline.policies import BearerTokenCredentialPolicy, HttpLoggingPolicy, RedirectPolicy  
from azure.core.pipeline.transport import RequestsTransport
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
import logging
from azure.core.pipeline.policies import UserAgentPolicy, NetworkTraceLoggingPolicy
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("azure.identity")
logger.setLevel(logging.DEBUG)

credential = DefaultAzureCredential()
credential_policy = BearerTokenCredentialPolicy(credential, 'https://graph.microsoft.com/.default')

policies = [
    UserAgentPolicy("SSCPlusDrupal"),  
    NetworkTraceLoggingPolicy(), 
    credential_policy,
    HttpLoggingPolicy(),
    RedirectPolicy()
]

transport = RequestsTransport(connection_verify=False)
pipeline = Pipeline(transport=transport, policies=policies) 
request = HttpRequest('GET', 'https://plus-dev.ssc-spc.gc.ca/rest/all-ids')
response = pipeline.run(request)

# Get the response  
print("RESPONSE HTTP CODE: " + str(response.http_response.status_code)) 
print("RESPONSE BODY: " + str(response.http_response.headers))
print(response.http_response.text())
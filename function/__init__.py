from azure.core.pipeline import Pipeline
from azure.core.pipeline.transport import HttpRequest, HttpResponse
from azure.core.pipeline.policies import BearerTokenCredentialPolicy, HttpLoggingPolicy
from azure.core.pipeline.transport import RequestsTransport
from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
import logging

logger = logging.getLogger("azure.identity")
logger.setLevel(logging.DEBUG)

credential = DefaultAzureCredential()
credential_policy = BearerTokenCredentialPolicy(credential, 'https://plus-dev.ssc-spc.gc.ca/.default')

policies = [
    credential_policy,
    HttpLoggingPolicy()
]

transport = RequestsTransport()#connection_verify=False)
pipeline = Pipeline(transport=transport, policies=policies) 
request = HttpRequest('GET', 'https://plus-dev.ssc-spc.gc.ca/rest/all-ids')
response = pipeline.run(request)

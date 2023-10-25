import json
import logging
import os
from datetime import datetime
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain.chat_models import AzureChatOpenAI
from langchain.embeddings import OpenAIEmbeddings
from llama_index import (LangchainEmbedding, LLMPredictor, ServiceContext,
                         SimpleDirectoryReader, VectorStoreIndex,
                         set_global_service_context)
from llama_index.callbacks import CallbackManager, LlamaDebugHandler
import openai

from azure.core.pipeline.policies import BearerTokenCredentialPolicy  
from azure.core.pipeline import Pipeline  
from azure.core.pipeline.transport import HttpRequest, RequestsTransport  
from azure.core.pipeline.policies import UserAgentPolicy, NetworkTraceLoggingPolicy, HttpLoggingPolicy
import requests  
import msal

load_dotenv()

#logging.basicConfig(level=logging.DEBUG)
#logging.getLogger("msal").setLevel(logging.WARN)

# login azure to obtain keyvault secret
credential     = DefaultAzureCredential()
key_vault_name = os.environ["KEY_VAULT_NAME"]
client         = SecretClient(vault_url=f"https://{key_vault_name}.vault.azure.net", credential=credential)

# bootstrap openai variables that will be needed for this exercise
openai_endpoint_name    = os.environ["OPENAI_ENDPOINT_NAME"]
azure_openai_key   = client.get_secret(os.getenv("OPENAI_KEY_NAME", "AzureOpenAIKey")).value

openai.api_type    = os.environ["OPENAI_API_TYPE"]    = 'azure'
openai.api_base    = os.environ["OPENAI_API_BASE"]    = f"https://{openai_endpoint_name}.openai.azure.com"
openai.api_version = os.environ["OPENAI_API_VERSION"] = "2023-07-01-preview"
openai.api_key     = os.environ["OPENAI_API_KEY"]     = azure_openai_key # type: ignore

pages = {}

def _get_all_ids():
    """
    get all ids from the https://plus-test.ssc-spc.gc.ca/en/rest/all-ids call
    
    refine process so we can be more selective about the ids we retreive... 
    produce a list that we will be looking at, specifically re-indexing a specific portion.
    •	/rest/updated-ids/week
      o	same
      o	updated with past 7 days
    •	/rest/updated-ids/month
      o	same
      o	updated within last 30 days
    """

    ids = []

    print("Getting all ids that need to be processed...")
    # TODO: do an actual call here..
    f = open("preload/ids-2023-10-17.json")
    data = json.load(f)
    for d in data:
        ids.append((d["nid"], d["type"]))

    #return ids
    return [(336, "article"), (534, "gigabit"), (703, "structured_page")]

def _download_pages(ids):
    """
    Will query the https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/336 API
    we make two separate calls, 1 for en and 1 for fr content.
    """
    for id in ids:
        print("Loading in https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/" + str(id[0]) + " type ==> " + id[1])
        # save page in preload/<type>/en/<id>.json
        print("Loading in https://plus-test.ssc-spc.gc.ca/fr/rest/page-by-id/" + str(id[0]) + " type ==> " + id[1])
        # save page in preload/<type>/fr/<id>.json

def _parse_pages(ids) -> dict:
    """
    for the purpose of this exercise there is so few pages that we can load all of them into memory
    we also have to split them into two separate page, each id gives us english and french and for 
    the purpose of metadata and searching its better if they are split in the index
    """
    # make sure dir and/or subdir exists..
    Path("data/en").mkdir(parents=True, exist_ok=True)
    Path("data/fr").mkdir(parents=True, exist_ok=True)

    ignore_selectors = ['div.comment-login-message', 'section.block-date-modified-block']

    for id in ids:
        for lang in ["en", "fr"]:
            f = open(''.join(["preload/", str(id[1]), "/", lang, "/", str(id[0]), ".json"]))
            data = json.load(f)
            for d in data:
                soup = BeautifulSoup(d["body"], "html.parser")
                # remove useless tags like date modified and login blocks (see example in 336 parsed data vs non parsed)
                for selector in ignore_selectors:
                    for s in soup.select(selector):
                        s.decompose()
                metadata = {
                    "title": str(d["title"]).strip(),
                    "url": str(d["url"]).strip(),
                    "date": str(d["date"]).strip() # TODO: date seems to be inconcistent field, might need some parsing, verify with Peter
                }
                filepath = "data/{}/{}".format(lang, d["nid"])
                pages[filepath] = metadata
                with open(filepath, 'w') as f:
                    f.write(' '.join(soup.stripped_strings))
    return pages

def _build_index():
    """
    read the data folder and builds the vector index to be used by the chatbot.
    """
    documents = SimpleDirectoryReader(input_dir='data', recursive=True, file_metadata=_metadata).load_data()

    """
    store documents into a vector store.
    note MS CognitiveSearchVectorStore: 
        * https://learn.microsoft.com/en-us/azure/search/search-get-started-vector
        * https://gpt-index.readthedocs.io/en/stable/community/integrations/vector_stores.html#using-a-vector-store-as-an-index
    """
    set_global_service_context(_get_service_context("gpt-4", 8192))
    index = VectorStoreIndex.from_documents(documents)
    date = datetime.now().strftime("%Y-%m-%d")
    print("Storage name: {}".format(date))
    index.storage_context.persist(persist_dir="storage/" + date)

def _metadata(filename: str) -> dict:
    print(filename)
    return pages[filename] 

def _get_service_context(model: str, context_window: int, temperature: float = 0.7, num_output: int = 800) -> "ServiceContext":
    chunk_overlap_ratio = 0.1 # overlap for each token fragment

    # using same dep as model name because of an older bug in langchains lib (now fixed I believe)
    llm = _get_llm(model, temperature)

    llm_predictor = _get_llm_predictor(llm)

    # limit is chunk size 1 atm
    embedding_llm = LangchainEmbedding(
        OpenAIEmbeddings(
            model="text-embedding-ada-002", 
            deployment="text-embedding-ada-002", 
            openai_api_key=openai.api_key,
            openai_api_base=openai.api_base,
            openai_api_type=openai.api_type,
            openai_api_version=openai.api_version),
            embed_batch_size=1)
    
    llama_debug = LlamaDebugHandler(print_trace_on_end=True)
    callback_manager = CallbackManager([llama_debug])

    return ServiceContext.from_defaults(llm_predictor=llm_predictor, embed_model=embedding_llm, callback_manager=callback_manager)

def _get_llm(model: str, temperature: float = 0.7):
    return AzureChatOpenAI(model=model, 
                           deployment_name=model,
                           temperature=temperature,)

def _get_llm_predictor(llm) -> LLMPredictor:
    return LLMPredictor(llm=llm,)

"""
here be dragons
"""

# loads all the ids that need to be processed
ids = _get_all_ids()
# for each of the ids load the json content for them and then split the content into appropriate folder (en/fr)
_download_pages(ids)
pages = _parse_pages(ids)

# at this point the "data" folder is ready to be read and indexed.
_build_index()

# Define the scope  
# scope = "https://management.azure.com/.default"  
  
# # Define the request  
# request = HttpRequest("GET", "https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/703")  
  
# # Define the pipeline  
# pipeline = Pipeline(transport=RequestsTransport(connection_verify=False),  
#                     policies=[UserAgentPolicy(),  
#                               NetworkTraceLoggingPolicy(),  
#                               HttpLoggingPolicy(),  
#                               BearerTokenCredentialPolicy(credential, scope)])  
  
# # Send the request  
# response = pipeline.run(request)  
  
# # Print the response  
# print(response.http_response.text())  

# if response.http_response.status_code == 302:  
#     redirect_url = response.http_response.headers['Location']
#     print("REDIRECT LOC IS {}".format(redirect_url))
#     request = HttpRequest("GET", "https://plus-test.ssc-spc.gc.ca/" + redirect_url)  
#     response = pipeline.run(request)  
#     print(response.http_response.text()) 

# config = {
#     "authority": "https://login.microsoftonline.com/d05bc194-94bf-4ad6-ae2e-1db0f2e38f5e",
#     "client_id": os.getenv("CLIENT_ID"),
#     "username": os.getenv("USERNAME"),
#     "password": os.getenv("PASSWORD"),
#     "scope": ["User.Read"],    
#     "endpoint": "https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/336"
# }

# # Create a preferably long-lived app instance which maintains a token cache.
# app = msal.PublicClientApplication(
#     config["client_id"], authority=config["authority"],
#     # token_cache=...  # Default cache is in memory only.
#                        # You can learn how to use SerializableTokenCache from
#                        # https://msal-python.rtfd.io/en/latest/#msal.SerializableTokenCache
#     )

# # The pattern to acquire a token looks like this.
# result = None

# # Firstly, check the cache to see if this end user has signed in before
# accounts = app.get_accounts(username=config["username"])
# if accounts:
#     logging.info("Account(s) exists in cache, probably with token too. Let's try.")
#     result = app.acquire_token_silent(config["scope"], account=accounts[0])

# if not result:
#     logging.info("No suitable token exists in cache. Let's get a new one from AAD.")
#     # See this page for constraints of Username Password Flow.
#     # https://github.com/AzureAD/microsoft-authentication-library-for-python/wiki/Username-Password-Authentication
#     result = app.acquire_token_by_username_password(
#         config["username"], config["password"], scopes=config["scope"])

# if "access_token" in result:
#     # Calling graph using the access token
#     graph_data = requests.get(  # Use token to call downstream service
#         config["endpoint"],
#         headers={'Authorization': 'Bearer ' + result['access_token']},).json()
#     print("Graph API call result: %s" % json.dumps(graph_data, indent=2))
# else:
#     print(result.get("error"))
#     print(result.get("error_description"))
#     print(result.get("correlation_id"))  # You may need this when reporting a bug
#     if 65001 in result.get("error_codes", []):  # Not mean to be coded programatically, but...
#         # AAD requires user consent for U/P flow
#         print("Visit this to consent:", app.get_authorization_request_url(config["scope"]))
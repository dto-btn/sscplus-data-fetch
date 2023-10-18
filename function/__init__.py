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

load_dotenv()

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("msal").setLevel(logging.WARN)

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
    and get a json response of the page that has both en and fr in it.
    """
    for id in ids:
        print("Loading in https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/" + str(id[0]) + " type ==> " + id[1])
        # save page in preload/<type>/<id>.json

def _split_pages(ids) -> dict:
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
        print("Splitting https://plus-test.ssc-spc.gc.ca/en/rest/page-by-id/" + str(id[0]) + " type ==> " + id[1])
        f = open(''.join(["preload/", str(id[1]), "/", str(id[0]), ".json"]))
        data = json.load(f)
        for d in data:
            soup = BeautifulSoup(d["body"], "html.parser")
            # remove useless tags like date modified and login blocks (see example in 336 parsed data vs non parsed)
            for selector in ignore_selectors:
                for s in soup.select(selector):
                    s.decompose()
            metadata = {
                "title": d["title"],
                "url": d["url"],
                "date": d["date"] # TODO: date seems to be inconcistent field, might need some parsing, verify with Peter
            }
            filepath = "data/{}/{}".format(d["langcode"], d["nid"])
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
pages = _split_pages(ids)

# at this point the "data" folder is ready to be read and indexed.
_build_index()
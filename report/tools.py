from pydantic import BaseModel, Field
import requests
from typing import Optional
import base64
from utils.chunker import chunk_tree
from agents import Agent, Runner, trace, OpenAIChatCompletionsModel, function_tool
import os
from db.qdrant import store_docs
import logging
import time
import certifi

logger = logging.getLogger(__name__)

HEADERS = {"Authorization": os.getenv('Github_access_token')}

# Replace all standalone requests.get calls with this session
session = requests.Session()
session.verify = certifi.where()

class Navigated_Repository(BaseModel):
    list_url: Optional[list[dict]]
    content : Optional[str]

@function_tool
def return_file_structure(user: str, repository_name:str, branch: str):
    '''
    When to call this function->
    After reading the Readme of the repository to understand the repository structure

    What to pass in this function->
    1. user : owner of the repository
    2. repository_name : repository name as given on GitHub
    3. branch : e.g. (main or master)
    ** try running for main if it returns error try running for master
    
    What does the function return->
    returns the string of the repository structure e.g. (Readme.md Blob \n asset tree)

    What to do next after calling this function->
    Use the tool navigate_repository to explore and understand the repo
    '''

    repo_url=f'https://api.github.com/repos/{user}/{repository_name}/git/trees/{branch}?recursive=1'
    logger.info("return_file_structure — user=%s repo=%s branch=%s", user, repository_name, branch)
    t0 = time.perf_counter()
    response=session.get(repo_url, headers=HEADERS)
    logger.info("return_file_structure — GitHub responded %s in %.2fs", response.status_code, time.perf_counter() - t0)
    data=response.json()

    structure_string=''

    for item in data["tree"]:
        structure_string+=f'''{item['path']}  {item['type']} \n'''

    logger.info("return_file_structure — returned %s entries", len(data["tree"]))
    return structure_string

@function_tool
def get_readme(user:str, repository_name:str):
    '''
    When to call->
    Always call this FIRST before any other tool.

    What to pass in->
    1. user : GitHub username or org name e.g. (https://github.com/zju3dv/pvnet here name is zju3dv)
    2. repository_name : exact repository name as on GitHub e.g. (https://github.com/zju3dv/pvnet here repository_name is pvnet)

    What does it return->
    str : full decoded README content, or 'Readme not found' if absent.

    What to do next->
    Call return_file_structure to map the full repo, using README 
    as context for which files matter.    
    '''

    url=f'''https://api.github.com/repos/{user}/{repository_name}/contents/'''
    logger.info("get_readme — user=%s repo=%s", user, repository_name)
    t0 = time.perf_counter()
    response=session.get(url, headers=HEADERS)
    logger.info("get_readme — GitHub responded %s in %.2fs", response.status_code, time.perf_counter() - t0)
    Data=response.json()

    content='Readme not found'
    for data in Data:
        readme_check=data['name'].lower()
        if readme_check=='readme.md':
            url=data['url']
            logger.info("get_readme — fetching README content from %s", url)
            result=session.get(url, headers=HEADERS)
            result=result.json()
            content=result['content']
            content=base64.b64decode(content).decode("utf-8")
            logger.info("get_readme — decoded README: %s chars", len(content))

    if content == 'Readme not found':
        logger.warning("get_readme — no README.md found in %s/%s", user, repository_name)
    return content


@function_tool
def navigate_repository(url:str, file_type : str)-> Navigated_Repository:
    '''
    When to call? ->
    One you have to navigate a tree or to get the content of blob

    When not to call ->
    Do NOT call this tool for files such as:
    README.md, LICENSE, .gitignore, images (.png, .jpg), PDFs, videos, binaries, or documentation files.
    
    What to pass in the function?->
    1. url : GitHub API contents URL only. Must follow this format:
         https://api.github.com/repos/{user}/{repo}/contents/{path}
         
         NOT the HTML url (https://github.com/...) 
         Use URLs returned by return_file_structure or previous navigate_repository calls.
         Never construct URLs manually.

    2. file_type : the type of the file the url is pointing towards (blob/tree)
    
    What does the function return->
    list_url : list of the child URLs present within the given url
    content : if the url file_type is a blob then return the content

    After calling this function? ->
    file_type='tree' → make parallel navigate_repository calls on each URL in list_url
    file_type='blob' → Call the create_chunk function tool and after creating chunks, pass content to the Parent agent, continue remaining trees. 
    '''


    logger.info("navigate_repository — url=%s type=%s", url, file_type)
    t0 = time.perf_counter()
    response=session.get(url, headers=HEADERS)
    logger.info("navigate_repository — GitHub responded %s in %.2fs", response.status_code, time.perf_counter() - t0)
    Data=response.json()

    content=None
    response_list=[]

    if file_type=='tree':
        for data in Data:
            response_list.append({'name' : data.get('name'), 'URL' : data.get('url')})
        logger.info("navigate_repository — tree has %s children", len(response_list))

    if file_type=='blob':
        content=base64.b64decode(Data['content']).decode("utf-8")
        logger.info("navigate_repository — blob decoded: %s chars", len(content))

    return Navigated_Repository(list_url=response_list, content=content)


@function_tool
def create_chunks(content : str, language : str, filename:str):
    '''
    When to call:
    After Navigation_repo, to store the content as chunks in the Vector DB

    What to pass:
    1. content : this represents the content sent by the Navigation_repo.
    2. language : the coding language used in the content e.g.(Python, Java, C++)
    3. filename : name of the file as given in the repo from where the content is read. e.g. for url : https://api.github.com/repos/zju3dv/pvnet/contents/run.py?ref=master filename is 'run.py'
    
    What does the funcition return:
    The fuction tool is used for creating chunks and storing it in Vector DB

    After calling the function:
    After calling the function continue the Navigation_repo to explore the rest of the repository
    '''
    logger.info("create_chunks — filename=%s language=%s content_len=%s", filename, language, len(content))
    t0 = time.perf_counter()
    try:
        chunks = chunk_tree(content, language.lower(), file_name=filename)
        logger.info("create_chunks — AST produced %s chunks for %s", len(chunks), filename)
        store_docs(chunks=chunks)
        logger.info("create_chunks — stored %s chunks in %.2fs for %s", len(chunks), time.perf_counter() - t0, filename)
        return('Created a chunk')

    except Exception as e:
        logger.exception('create_chunks failed filename=%s error=%s', filename, e)
        return('Error occurred')
import jwt
import time
import requests
import json
import asyncio
from typing import List
from abc import ABC, abstractmethod
from datetime import datetime

from requests.models import HTTPError

class BulkAPIConnectionSettings():
    def __init__(self, private_key: str, consumer_key: str, audience:str, username:str,api_version:str):
        self.private_key  = private_key
        self.consumer_key = consumer_key
        self.audience     = audience
        self.username     = username
        self.api_version  = api_version


class BulkAPIConnection():
    '''
    Connects to the Salesforce Bulk API
    '''
    def __init__(self, connection_settings:BulkAPIConnectionSettings):
        self.settings = connection_settings
        self.__oauth_response = self.__get_oauth2_response()

    def __get_oauth2_response(self):
        private_key=self.settings.private_key

        claim = {
            'iss': self.settings.consumer_key, # This is the consumer key
            'exp': int(time.time()) + 300,
            'aud': self.settings.audience,
            'sub': self.settings.username,
        }
        assertion = jwt.encode(claim, private_key, algorithm='RS256', headers={'alg':'RS256'})

        r = requests.post(f'{self.settings.audience}/services/oauth2/token', data = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': assertion,
        })

        return r.json()

    def refresh_credentials(self) -> None:
        self.__oauth_response = self.__get_oauth2_response()
    
    @property
    def headers(self):
        return {
        'Authorization': 'Bearer ' + self.access_token,
        'Content-Type': 'application/json',
        }  

    @property
    def access_token(self) -> str:
        return self.__oauth_response['access_token']

    @property
    def instance_url(self) ->str:
        return self.__oauth_response['instance_url']

    def get_all_objects(self) -> List[str]:
        headers = self.headers
        req = requests.get(f'{self.instance_url}/services/data/{self.settings.api_version}/sobjects',headers=headers)
        req.raise_for_status()
        return [elem['name'] for elem in req.json()['sobjects'] if elem['queryable']==True]
    

class SalesforceObject():
    '''
    Wrapper around a Salesforce object
    '''
    def __init__(self, name:str, connection:BulkAPIConnection):
        self.name = name
        self.connection = connection

    def describe(self):
        headers = self.connection.headers
        req = requests.get(f'{self.connection.instance_url}/services/data/{self.connection.settings.api_version}/sobjects/{self.name}/describe',headers=headers)
        req.raise_for_status()
        return req.json()

    @property
    def columns(self, exclude_compound=True, exclude_calculated=True):
        describe = self.describe()
        columns = set([x['name'] for x in describe['fields']])

        if exclude_calculated:
            calculated_columns = set([x['name'] for x in describe['fields'] if (x['calculated']==True)])
            columns.difference_update(list(calculated_columns))

        if exclude_compound:
            compound_columns = set([x['compoundFieldName'] for x in describe['fields']])
            columns.difference_update(list(compound_columns))
        
        return columns


class BulkAPIJob():
    '''
    Salesforce API Batch job
    Documentation: https://developer.salesforce.com/docs/atlas.en-us.api_asynch.meta/api_asynch/query_create_job.htm
    '''
    def __init__(self,object:SalesforceObject,connection:BulkAPIConnection) -> None:
        self.connection = connection
        self._on_complete = JobCompleteEvent()
        self.object = object
        self.id = None

    async def status(self):
        loop = asyncio.get_event_loop()
        f3=loop.run_in_executor(None,lambda:requests.get(f"{self.connection.instance_url}/services/data/{self.connection.settings.api_version}/jobs/query/{self.id}",headers=self.connection.headers))
        req = await f3
        req.raise_for_status()
        return req.json()['state']
        

    async def start(self):
        print(f'Starting job for {self.object.name}')

        loop = asyncio.get_event_loop()
        f1=loop.run_in_executor(None,lambda: requests.post(
            f"{self.connection.instance_url}/services/data/{self.connection.settings.api_version}/jobs/query",
            data=json.dumps(self.body),
            headers=self.connection.headers
        ))
        req = await f1

        try:
            req.raise_for_status()
        except HTTPError as e:
            if json.loads(e.response.content)[0]['errorCode']=='INVALIDENTITY':
                return
            elif json.loads(e.response.content)[0]['errorCode']=='API_ERROR':
                return
            elif json.loads(e.response.content)[0]['errorCode']=='INVALIDJOB':
                return
            else:
                raise
            
        self.id = req.json()['id']
        delay_iter = iter([1,1,10,30,60])
        
        while True:
            try:
                delay = next(delay_iter)
            except StopIteration:
                delay = delay

            await asyncio.sleep(delay)

            status = await self.status()
            print(f'{self.object.name}: {status}')

            if status=='Failed':
                break

            if status=='JobComplete':
                await self.on_complete(f"{self.connection.instance_url}/services/data/{self.connection.settings.api_version}/jobs/query/{self.id}/results",self)
                print(f'Finished job for {self.object.name}')
                break 
        return 0
        
    @property
    def body(self):
        return {
        "operation": "query",
        "query": self.query
        }

    @property
    @abstractmethod
    def query(self):
        return NotImplemented

    @property
    def token(self):
        return self._oauth2_response['access_token']

    @property
    def instance(self):
        return self._oauth2_response['instance_url']
    
    @property
    def on_complete(self):
        return self._on_complete


class GetAllBulkAPIJob(BulkAPIJob):

    @property
    def query(self):
        return "SELECT " + ', '.join(self.object.columns) +" FROM " + self.object.name


class BulkAPIResultHandler(ABC):
    '''
    Handles results from a the BulkAPIJob via handle()
    '''

    def __init__(self,result_url:str,job:BulkAPIJob) -> None:
        self.result_url = result_url
        self.batch_number = 0
        self.job = job

    async def fetch(self):
        loop = asyncio.get_event_loop()
        f1=loop.run_in_executor(None,lambda: requests.get(f"{self.result_url}?maxRecords=50000",headers=self.job.connection.headers))

        self.datetime_start_fetch = datetime.now()
        result = await f1
        self.handle(result)
        while 'sforce-locator' in result.headers.keys():
            if (result.headers['sforce-locator']!='NA') & (result.headers['sforce-locator']!='null'):     
                self.batch_number += 1  
                f2=loop.run_in_executor(None,lambda: requests.get(f"{self.result_url}?locator={result.headers['sforce-locator']}&maxRecords=50000",headers=self.job.connection.headers))
                result=await f2
                self.handle(result)
            else:
                break

    @abstractmethod 
    def handle(self,data):
        return NotImplemented


class JobCompleteEvent(List[BulkAPIResultHandler]):
    
    async def __call__(self, *args, **kwargs):
        for c in self:
            i=c(*args,*kwargs)
            await i.fetch()

    def __repr__(self):
        return "Event(%s)" % list.__repr__(self)

class JobQueue(list):

    def __init__(self,parallel_jobs:int=10):
        self.parallel_jobs = parallel_jobs
        super().__init__()

    async def run_all(self):
        while True:
            set_to_run = self[0:self.parallel_jobs]
            if set_to_run!=[]:
                for elem in set_to_run:
                    self.remove(elem)
                await asyncio.gather(
                    *[x.start() for x in set_to_run]
                )
            else:
                break
                


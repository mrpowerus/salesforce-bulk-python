from _pytest.fixtures import fixture
import pytest
from salesforce_bulk_python.bulk import BulkAPIConnection, BulkAPIConnectionSettings, BulkAPIResultHandler, SalesforceObject, GetAllBulkAPIJob, JobQueue
import os
import asyncio

@fixture
def connection_settings():
    return BulkAPIConnectionSettings(
        private_key  = os.environ['SF_PRIVATE_KEY'],
        consumer_key = os.environ['SF_CONSUMER_KEY'],
        audience     = 'https://test.salesforce.com',
        username     = os.environ['SF_USERNAME'],
        api_version  = 'v52.0'
    )

@fixture
def connection(connection_settings): 
    return BulkAPIConnection(connection_settings)

@fixture
def object(connection_settings:BulkAPIConnectionSettings):
    con = BulkAPIConnection(connection_settings)
    return SalesforceObject('Account', con)

@fixture
def job(object:SalesforceObject,connection:BulkAPIConnectionSettings):
    return GetAllBulkAPIJob(object,connection)

@fixture
def handler():
    class Handler(BulkAPIResultHandler):
        def handle(self, data):
            print(data)
    return Handler

@fixture
def queue():
    return JobQueue()


class TestBulkAPIConnection:

    def test_access_token(self,connection:BulkAPIConnection):
        assert connection.access_token

    def test_get_all_objects(self,connection:BulkAPIConnection):
        assert connection.get_all_objects()

    def test_refresh_credentials(self,connection:BulkAPIConnection):
        connection.refresh_credentials()


class TestSalesforceObject:

    def test_describe(self,object:SalesforceObject):
        assert object.describe()

    def test_columns(self,object:SalesforceObject):
        assert object.columns
    

class TestBulkAPIJob:
    def test_getjob(self,job:GetAllBulkAPIJob,handler:BulkAPIResultHandler):
        job.on_complete.append(handler)
        asyncio.run(job.start())

class TestJobQueue:
    def test_run_all(self,queue:JobQueue,job:GetAllBulkAPIJob):
        queue.append(job)
        queue.append(job)
        asyncio.run(queue.run_all())
Salesforce Bulk Python
======================

Salesforce Bulk Python is a Python library for using the Salesforce REST Bulk API v2.0. It is especially designed to handle big-data worksloads, in which all data from Salesforce should be extraced.

It makes uses of asyncio for parallel execution. And is easily exendable by writing your own `BulkAPIResultHandler`.

# How to use

### 1. Authentication


This library currently only supports the [OAuth 2.0 JWT Bearer Flow](https://help.salesforce.com/articleView?id=sf.remoteaccess_oauth_jwt_flow.htm&type=5). 

```python
connection_settings = BulkAPIConnectionSettings(
    private_key  = <KEY HERE>, # Private key to encode the JWT with (used by jwt.encode())
    consumer_key = <CONSUMER KEY HERE>, # Consumer Key Created by Connected App
    audience     = <SALESFORCE DOMAIN>, # Example: https://test.salesforce.com
    username     = <USERNAME>, # User that is assigned to the app
    api_version  = <API VERSION> # Example: v52.0
)
```

### 2. Create a connection

Create a connection by passing `BulkAPIConnectionSettings` into a `BulkAPIConnection`.

```python
con = BulkAPIConnection(connection_settings)
```

### 3. Get a reference to an Salesforce object
```python
# Get one object
obj = SalesforceObject('Account', con)

# or... get a List[SalesforceObject] from all objects that are compatible with the Bulk API v2.0
all_obj = list([SalesforceObject(x,con) for x in con.get_all_objects()])
```

### 4. Create an `BulkAPIResultHandler` and implement the `handle` method.

The `BulkAPIResultHandler` will do something with the responses from the Bulk API.

For example, we could write the responses to a Azure ADLS Gen2 Storage account:
```python
class ADLSHandler(BulkAPIResultHandler):
    def handle(self,data):
        datetime_start = datetime.now()
        file_name = f'/salesforce/{self.job.object.name}/timestamp={datetime_start}/{self.batch_number}.csv'
        adls.raw.client.create_file(filename).upload_data(data.content,overwrite=True)

```

### 5. Create a job and register the handler

We currently only support the `GetAllBulkAPIJob` but you can subclass the `BulkAPIJob` yourself and implement a custom `query` method.

```python
  job1 = GetAllBulkAPIJob(obj,con)
  job1.on_complete.append(ADLSHandler)

  job2 = GetAllBulkAPIJob(obj,con)
  job2.on_complete.append(ADLSHandler)
```

### 6. Execute one single job, or run multiple jobs in parralel.
```python
# Run only one job
asyncio.run(job.start())

# Run multiple jobs in parralel
q = JobQueue(parallel_jobs=10)
q.extend([job1, job2])
asyncio.run(q.run_all())
```

When the jobs above are executed, the results will be passed to the handler.



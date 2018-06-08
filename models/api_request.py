import json
import socket
from odoo.addons.odoo_magento2_ept.python_library import requests
import logging
from odoo.addons.odoo_magento2_ept.models.backend.exception import (
                                                                    NetworkRetryableError,
                                                                    FailedJobError,
                                                                   )
from odoo.addons.odoo_magento2_ept.python_library.requests.exceptions import HTTPError
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)
def req(backend,path,method='GET',data=None,params=None):
    location_url = backend._check_location_url(backend.location)
    api_url =  '%s%s'%(location_url,path)
    headers = {'Accept': '*/*', 'Content-Type': 'application/json','Authorization':'Bearer %s'%backend.token}
    try :
        #resp, content = client.request(api_url,method=method, body=json.dumps(data),headers=headers)
        _logger.info('Data pass to Magento : %s'%data)
        if method == 'GET' :
            resp = requests.get(api_url,headers=headers,verify=False,params=params)
        elif method == 'POST':
            resp = requests.post(api_url,headers=headers,data=json.dumps(data),verify=False,params=params)
        elif method == 'DELETE':
            resp = requests.delete(api_url,headers=headers,verify=False,params=params)
        elif method == 'PUT' :
            resp = requests.put(api_url,headers=headers,data=json.dumps(data),verify=False,params=params)
        else :
            resp = requests.get(api_url,headers=headers,verify=False,params=params)
        content = resp.json()
        _logger.info('Response status code from Magento : %s',
                     resp.status_code)
        _logger.info('Content : %s'%content)
        _logger.info('API URL : %s'%api_url)
        _logger.info('Response Status code : %s'%resp.status_code)
        if resp.status_code == 401:
            raise FailedJobError('Given Credentials is incorrect, please provide correct Credentials.')
        if not resp.ok :
            if resp.headers.get('content-type').split(';')[0] == 'text/html' :
                raise FailedJobError("Content-type is not JSON \n %s : %s \n %s \n %s"%(resp.status_code,resp.reason,path,resp.content))
            else :
                response = resp.json()
                response.update({'status_code':resp.status_code})
                raise HTTPError(str(response),response=response)      
    except HTTPError as err:
        response = err.response
        raise FailedJobError("Request is not Satisfied : \n Status Code : %s \n Content : %s"%(response.get('status_code'),response.get('message')))
    except (socket.gaierror, socket.error, socket.timeout) as err :
        raise NetworkRetryableError(
                'A network error caused the failure of the job: '
                '%s' % err)
   
    return content


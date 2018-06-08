def create_filter(field,value,condition_type='eq'):
    filter_dict = {}
    filter_dict['field']=field
    if isinstance(value, str) and condition_type == "in":
        filter_dict['condition_type']='like'
    elif isinstance(value, str) and condition_type == "nin":
        filter_dict['condition_type']='nlike'
    else :
        filter_dict['condition_type']=condition_type
    filter_dict['value']=value

    return filter_dict

def create_search_criteria(filters):
    """
        Create Search Criteria
        if filters is {'updated_at': {'to': '2016-12-22 10:42:44', 'from': '2016-12-16 10:42:18'}}
        then searchCriteria = {'searchCriteria': {'filterGroups': [{'filters': [{'field': 'updated_at', 'condition_type': 'to', 'value': '2016-12-22 10:42:44'}]}, {'filters': [{'field': 'updated_at', 'condition_type': 'from', 'value': '2016-12-16 10:42:18'}]}]}}
    """
    searchcriteria = {}
    if filters is None :
            filters = {}
        
    if not filters:
        searchcriteria =  {'searchCriteria':{'filterGroups':[{'filters':[{'field':'id','value':-1,'condition_type':'gt'}]}]}}
    else :
        searchcriteria.setdefault('searchCriteria',{})
        filtersgroup_list = []
        for k,v in filters.items() :
            tempfilters = {}
            filters_list = []
            condition = {}
            if isinstance(v,dict):
                for operator,values in v.items() :
                    if isinstance(values, list) :
                        if operator == "in" :
                            for value in values :
                                filters_list.append(create_filter(k, value, operator))
                            tempfilters["filters"]=filters_list
                            filtersgroup_list.append(tempfilters)
                        elif operator == "nin" :
                            for value in values :
                                filters_list.append(create_filter(k, value, operator))
                                tempfilters["filters"]=filters_list
                                filtersgroup_list.append(tempfilters)
                    else :
                        filters_list.append(create_filter(k, values, operator))
                        tempfilters["filters"]=filters_list
                        filtersgroup_list.append(tempfilters)
                        filters_list=[]
                        tempfilters={}
            else :
                filters_list.append(create_filter(k, v))
                tempfilters["filters"]=filters_list
                filtersgroup_list.append(tempfilters)
        searchcriteria["searchCriteria"]['filterGroups']=filtersgroup_list
    return searchcriteria

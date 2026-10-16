import json
import unittest
import urllib.error
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mcd_mcp import (MCPClient,MCPError,find_orders,latest_valid_order,order_items,
    extract_json,parse_envelope,unwrap_tool_result,fetch_latest_items)

class DummyResponse:
    headers={'Content-Type':'application/json'}
    def __init__(self,data):self.data=json.dumps(data).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.data[:limit]

class MCPTests(unittest.TestCase):
    def test_extract_wrapped_json(self):
        example='# API Response Information\n{"example":{"schema":"not real"}}\n## Original Response\n{"data":{"list":[]}}'
        self.assertEqual(extract_json(example),{'data':{'list':[]}})
        self.assertEqual(extract_json('here is {"a":1} trailing'),{'a':1})
        with self.assertRaises(MCPError):extract_json('no json here')

    def test_parse_sse_json(self):
        raw=': keepalive\n\ndata: {"jsonrpc":"2.0","result":{"a":1}}\n\n'
        self.assertEqual(parse_envelope(raw,'text/event-stream')['result'],{'a':1})
        multi='data: {"jsonrpc":"2.0",\ndata: "result": {"ok":true}}\n\n'
        self.assertTrue(parse_envelope(multi,'text/event-stream')['result']['ok'])
        with self.assertRaises(MCPError):parse_envelope('broken json','application/json')

    def test_unwrap(self):
        self.assertEqual(unwrap_tool_result({'structuredContent':{'data':{'list':[]}}}),{'data':{'list':[]}})
        self.assertEqual(unwrap_tool_result({'content':[{'type':'text','text':'## Original Response\n{"data":{}}'}]}),{'data':{}})
        with self.assertRaises(MCPError):unwrap_tool_result({'isError':True,'content':[]})

    def test_order_select(self):
        samples={'data':{'list':[
          {'orderId':'a','createTime':'2026-10-12 11:00:00','orderStatus':'已取消','orderProductList':[]},
          {'orderId':'b','createTime':'2026-10-14 11:00:00','orderStatus':'已完成','orderProductList':[]},
          {'orderId':'c','createTime':'2026-10-13 11:00:00','orderStatus':'已完成','orderProductList':[]}]}}
        self.assertEqual(latest_valid_order(samples)['orderId'],'b')
        self.assertIsNone(latest_valid_order({'data':{'list':[samples['data']['list'][0]]}}))
        self.assertIsNone(latest_valid_order({'data':{}}))
        self.assertEqual(find_orders({'result':{'records':[samples['data']['list'][0]]}})[0]['orderId'],'a')

    def test_combo_and_quantities(self):
        parent={'orderProductList':[{'productName':'巨无霸套餐','quantity':2,'comboItemList':[
          {'productName':'巨无霸','quantity':1},{'productName':'中薯条','quantity':1},{'productName':'可乐','quantity':1}]},
          {'productName':'巨无霸','quantity':1}]}
        got=order_items(parent)
        self.assertEqual([(i.name,i.quantity) for i in got],[('巨无霸',3),('中薯条',2),('可乐',2)])

    def test_combo_alias_fields(self):
        """子项写成 itemName/itemQuantity 时也要展开。

        接口不同版本/不同接口的字段命名不一致。只认 productName 的话，
        子项会被整段跳过，然后**静默**退回父套餐名 —— 不报错，但结果是错的：
        本该是「中薯条 + 可乐」，却输出「巨无霸套餐 ×2」。
        """
        parent={'orderProductList':[{'itemName':'巨无霸套餐','itemQuantity':2,'comboItemList':[
          {'itemName':'中薯条','itemQuantity':1},{'itemName':'可乐','itemQuantity':1}]}]}
        got=order_items(parent)
        self.assertEqual([(i.name,i.quantity) for i in got],[('中薯条',2),('可乐',2)])
        self.assertNotIn('巨无霸套餐',[i.name for i in got])

    def test_combo_mixed_field_names(self):
        """父项用一套命名、子项用另一套，也得能对上。"""
        parent={'orderProductList':[{'productName':'巨无霸套餐','quantity':1,'comboItemList':[
          {'itemName':'巨无霸','itemQuantity':1},{'name':'中薯条','quantity':2}]}]}
        got=order_items(parent)
        self.assertEqual([(i.name,i.quantity) for i in got],[('巨无霸',1),('中薯条',2)])

    def test_combo_alias_child_without_name(self):
        """别名都取不到名字时，仍按原逻辑退回父套餐名（不抛异常）。"""
        parent={'orderProductList':[{'productName':'巨无霸套餐','quantity':3,'comboItemList':[
          {'unknownKey':'中薯条','quantity':1}]}]}
        got=order_items(parent)
        self.assertEqual([(i.name,i.quantity) for i in got],[('巨无霸套餐',3)])

    def test_no_token(self):
        with self.assertRaises(MCPError):MCPClient(token='')

    def test_client_real_protocol_shape_with_mock(self):
        calls=[]
        def mock_opener(req,timeout):
            payload=json.loads(req.data)
            calls.append((payload,req.get_header('Authorization')))
            if payload['method']=='initialize':return DummyResponse({'jsonrpc':'2.0','id':1,'result':{'capabilities':{}}})
            if payload['method']=='notifications/initialized':return DummyResponse({})
            return DummyResponse({'jsonrpc':'2.0','id':2,'result':{'content':[{'type':'text','text':'## Original Response\n'+json.dumps({'data':{'list':[{'orderId':'unit','createTime':'2026-10-15 11:00','orderStatus':'已完成','orderProductList':[{'productName':'麦辣鸡腿堡','quantity':1}]}]}})}]}})
        client=MCPClient(token='TEST-LOCAL-NOT-REAL',opener=mock_opener)
        got=fetch_latest_items(client)
        self.assertEqual(got[0].name,'麦辣鸡腿堡')
        self.assertEqual([x[0]['method'] for x in calls],['initialize','notifications/initialized','tools/call'])
        self.assertEqual(calls[2][0]['params']['name'],'order-list')
        self.assertTrue(all(x[1]=='Bearer TEST-LOCAL-NOT-REAL' for x in calls))

    def test_http_error_no_secret(self):
        def deny(req,timeout):
            raise urllib.error.HTTPError(req.full_url,401,'secret-sensitive',{},None)
        client=MCPClient(token='PRIVATE-SECRET',opener=deny)
        with self.assertRaises(MCPError) as err:client.list_orders()
        self.assertNotIn('PRIVATE-SECRET',str(err.exception))
        self.assertIn('401',str(err.exception))

if __name__=='__main__':unittest.main()

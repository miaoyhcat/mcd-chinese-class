import json
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine

class EngineTests(unittest.TestCase):
    def test_lesson_catalog(self):
        ls=engine.load_lessons()
        self.assertEqual(len(ls),16)
        self.assertEqual(len({l['id'] for l in ls}),16)
        for l in ls:
            self.assertTrue(all(x in l for x in ['title','genre','opening','body','ending','inspired_by']))
            self.assertGreaterEqual(len(l['body']),3)

    def test_all_lessons_all_inputs(self):
        orders=[['巨无霸','中薯条','可乐'],['麦辣鸡腿堡','雪碧'],['水果派','矿泉水'],['抹茶派','奶茶'],['🍔套餐','𠮷野家'],['<script>alert(1)</script>','咖啡']]
        for l in engine.load_lessons():
            for order in orders:
                with self.subTest(lesson=l['id'],items=order):
                    doc=engine.compose(order,l['id'])
                    self.assertTrue(doc['body'])
                    self.assertTrue(doc['opening'].strip())
                    self.assertNotIn('{main}',json.dumps(doc))
                    self.assertNotIn('questions',doc)
                    self.assertNotIn('习题',engine.as_plain(doc))

    def test_classification(self):
        for name in ['水果派','抹茶派','苹果派']:
            self.assertEqual(engine.category(name),'side')
        for name in ['矿泉水','柠檬茶','可乐']:
            self.assertEqual(engine.category(name),'drink')
        for name in ['板烧鸡腿堡','巨无霸','麦香鱼']:
            self.assertEqual(engine.category(name),'main')

    def test_validation_and_quantities(self):
        items=engine.normalize_items([{'name':'巨无霸','quantity':2},{'name':'巨无霸','quantity':3},'薯条'])
        self.assertEqual(items[0].quantity,5)
        self.assertEqual(engine.normalize_items([{'name':'巨无霸','quantity':90},{'name':'巨无霸','quantity':20}])[0].quantity,99)
        self.assertEqual(engine.parse_items('巨无霸 ×2，薯条x3')[1].quantity,3)
        for sample in [[],[''],[{'name':'巨无霸','quantity':0}],[{'name':'巨无霸','quantity':False}],['a'*73],['a\nb']]:
            with self.subTest(sample=sample),self.assertRaises(engine.InputError):
                engine.normalize_items(sample)
        with self.assertRaises(engine.InputError): engine.normalize_items(['a'+str(i) for i in range(42)])

    def test_braces_in_user_input_are_literal(self):
        doc=engine.compose(['订单{not_a_template}','薯条'],'beiying')
        self.assertIn('订单{not_a_template}',doc['opening'])

    def test_deterministic(self):
        items=engine.parse_items('巨无霸,可乐,薯条')
        a=engine.compose(items)
        self.assertEqual(a,engine.compose(items))
        self.assertTrue(1<=a['number']<=999)
        self.assertEqual(a['number'],engine.stable_number(items))

    def test_sanitization(self):
        doc=engine.compose(['巨无霸','可乐'])
        obj=engine.browser_payload(doc['items'])
        self.assertEqual(set(obj),{'format','items'})
        raw=json.dumps(obj,ensure_ascii=False)
        for forbidden in ['orderId','storeName','phone','token','amount']:
            self.assertNotIn(forbidden,raw)
        self.assertIn('课文完',engine.as_plain(doc))
        self.assertIn('# ',engine.as_markdown(doc))

if __name__=='__main__':unittest.main()

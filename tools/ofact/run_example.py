import json
from pathlib import Path
import time

notebook=Path('/ofact/projects/tutorial/01_modelling/9_sales_generation.ipynb')
code='\n'.join(''.join(cell['source']) for cell in json.loads(notebook.read_text())['cells'] if cell['cell_type']=='code')
started=time.monotonic()
exec(compile(code,str(notebook),'exec'))
orders=state_model.get_orders()
customers=state_model.get_customers()
assert len(orders)==20
assert len(customers)>0
print(json.dumps({'upstream_notebook':str(notebook),'orders':len(orders),'customers':len(customers),'seconds':round(time.monotonic()-started,3)}))

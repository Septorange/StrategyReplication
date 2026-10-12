from __future__ import annotations
import math
import numpy as np
import pandas as pd
def records(frame:pd.DataFrame):
    x=frame.copy()
    for c in x.columns:
        if pd.api.types.is_datetime64_any_dtype(x[c]): x[c]=x[c].dt.strftime('%Y-%m-%d')
    return [{k:(None if pd.isna(v) else v.item() if isinstance(v,np.generic) else v) for k,v in row.items()} for row in x.to_dict('records')]
def metrics(r):
    r=pd.to_numeric(r,errors='coerce').dropna(); nav=(1+r).cumprod(); vol=r.std(ddof=1)*math.sqrt(252)
    return {'annualized_return':float(nav.iloc[-1]**(252/len(r))-1),'annualized_vol':float(vol),'sharpe':float(r.mean()/r.std(ddof=1)*math.sqrt(252)),'max_drawdown':float((nav/nav.cummax()-1).min()),'observations':int(len(r))}

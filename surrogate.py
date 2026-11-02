"""Tiny supervised residual-cost surrogate interface with exact safety fallback."""
import statistics
def fit(samples):
 if not samples: raise ValueError('样本不能为空')
 xs=[float(x['remaining']) for x in samples]; ys=[float(x['cost']) for x in samples]
 mean=statistics.mean(ys); slope=0 if len(set(xs))<2 else (statistics.mean((x-statistics.mean(xs))*(y-mean) for x,y in zip(xs,ys))/statistics.pvariance(xs))
 intercept=mean-slope*statistics.mean(xs)
 return {'version':'1.0','model':'linear-residual-cost','slope':slope,'intercept':intercept,'samples':len(samples)}
def predict(model,remaining): return model['intercept']+model['slope']*float(remaining)
def validate(model,samples):
 errors=[abs(predict(model,x['remaining'])-x['cost']) for x in samples]
 return {'mae':statistics.mean(errors) if errors else 0.0,'max_error':max(errors) if errors else 0.0,'samples':len(errors),'exact_safety_required':True}

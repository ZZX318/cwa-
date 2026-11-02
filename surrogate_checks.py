from surrogate import fit,predict,validate
def run():
 tr=[{'remaining':i,'cost':2*i+1} for i in range(5)]; m=fit(tr); v=validate(m,tr); assert predict(m,3)>0 and v['mae']<1e-9 and v['exact_safety_required']; print('通过 · 第十五阶段代理接口与误差验证'); return 0

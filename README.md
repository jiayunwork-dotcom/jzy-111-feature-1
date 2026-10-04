# 反射双曲线动校正（NMO）核算服务

常驻 HTTP 服务，只做水平层状介质反射波正常时差这一件事：给定零偏移距双程走时
`t0`、叠加速度 `v`、炮检距 `x`，核算反射走时与动校正量、浅层大偏移拉伸告警，
并支持整条双曲线铺线与候选叠加速度扫描。无网页、无工区管理、无测井台账。

在双曲近似之外，服务还接受**水平层状速度模型**（自上而下若干层，每层厚度 +
层速度），按斯奈尔定律追踪真实折射—反射射线，给出**精确射线走时**并与该界面
`t0`/均方根速度套出的双曲近似并排对比；模型界面可一键生成动校档，原有三个接口
拿档名照常可用。


## 内核公式

反射双曲线（非折射截距）：

```
t(x)² = t0² + x² / v²
Δt(x) = t(x) − t0
```

- 炮检距为零时 `Δt = 0`；炮检距正负均可，进公式的是平方。
- 拉伸标记：`Δt / t0 > threshold`（默认 0.10）时告警，走时仍照实返回，不拒绝。
- 曲线与扫描各点都调用单点内核，全服务同一套速度、同一条平方关系。
- 速度扫描：对每个候选速度算校正后走时 `t_corr(x) = t_obs(x) − sqrt(t0² + x²/v²)`，
  以各道相对零偏移道残差的均方值为平整度评分，正确事件速度评分最小（为 0）。

运行期可把常用 `(t0, velocity)` 命名为动校档反复调用，**纯内存、重启即丢**；
两份档相互独立，扫描时不串参数。

## 层状速度模型与精确射线走时

### 模型

模型自上而下 1~30 个水平层，每层给厚度与层速度（都必须是有限正数）。模型可以
起名字存起来反复用，**纯内存、重启即丢**，且与动校档**各管各的名字空间**：
模型 `A` 与动校档 `A` 同名互不覆盖。

每个层底界面给出（Dix 定义）：

```
t0(I)   = Σ_{i≤I} 2 h_i / v_i                       # 垂直双程走时
vrms(I) = sqrt( Σ_{i≤I} v_i²·(2 h_i/v_i) / t0(I) )  # 均方根速度
```

基准两层模型（上 1000 m/2000 m·s⁻¹、下 1000 m/3000 m·s⁻¹）第二界面：
`t0 = 5/3 s`、`vrms = sqrt(6 000 000) ≈ 2449.49 m/s`。

### 精确射线

射线参数 `p` 沿整条射线守恒（斯奈尔定律 `sin θ_i = p·v_i`）。给定 `p`：

```
X(p) = Σ p·h_i·v_i / sqrt(1−(p v_i)²)     # 单程半炮检距
T(p) = Σ 2·h_i / (v_i·sqrt(1−(p v_i)²)    # 双程走时
```

对请求炮检距 `x`（正负按绝对值处理），求解 `X(p)=|x|/2` 得到射线，返回
`ray_parameter`、`exact_traveltime`，同时用该界面的 `t0`/`vrms` 套双曲得到
`hyperbolic_traveltime = sqrt(t0² + x²/vrms²)` 以及两者之差
`traveltime_difference = 精确 − 双曲`。零炮检距时 `p=0`、精确走时严格等于
垂直双程走时。小炮检距时差为 `O(x⁴)`（该模型下精确走时位于 RMS 双曲线之下，
差为负），炮检距减半时差至少缩到 1/8；走时对炮检距的斜率处处等于射线参数：
`dt/dx = p`。

#### 射线参数怎么求：归一化 `s = p·vmax` + 几何括住 + 二分

`p` 的物理区间是 `[0, 1/vmax)`（`vmax` 为射线穿过各层的最快层速度），越接近
临界值 `1−(pv)²` 越接近零，直接对 `p` 求根容易在开方、除法上溢出或跑飞。
服务改用归一化射线参数：

```
s = p · vmax ∈ [0, 1)
```

- 根号稳定写法：`sqrt(1−r²)` 一律按 `sqrt((1−r)(1+r))` 计算。`1−r` 是独立
  保存的浮点量，而不是 `1−r²` 相消的结果，因此任意有限 `s<1` 下根号内都不丢
  精度、不会出现负值；真正的临界射线（炮检距无穷）在浮点上已无法继续向 1
  括住时，返回带原因的 400，而不是吐出一条错误射线。
- 括住办法：上界从 `s=0.5` 起，每次向 1 吃掉剩余 `(1−s)` 的一半
  （`s ← s + (1−s)/2`），直到半炮检距超过目标；`X(s)` 在 `[0,1)` 上严格
  单调（每一层项随 `s` 严格递增），根必被括住且唯一。
- 求根：随后二分到底（约 60 次区间折半，相对宽度约 1e-18）。

**选择理由**：不依赖对临界端点敏感的初值猜测，也不引入 scipy 等重依赖，镜像
保持一键构建；在 20 倍界面深度、5 倍以上层间速度差时复算炮检距与请求值之差
仍在毫米量级（实测 1e-9 m 级别）。**代价**：二分只有线性收敛，没有 Brent 那
类超线性收敛快——但每次迭代只是最多 30 层的乘加与开方，单请求约 60 次迭代，
对在线接口可以忽略；换来的是全程不溢出、不跑飞、必然收敛的确定性。

### 从界面生成动校档

`POST /velocity-models/profile` 取模型某界面的（垂直双程走时，均方根速度）
写入一套普通动校档。生成后 `POST /nmo/point`、`/nmo/curve`、`/nmo/scan`
拿该档名照常可用；拉伸告警口径、请求/返回字段、增删查行为全部不变。


## 镜像构建与运行（一键）

```bash
docker build -t nmo-service .
docker run --rm -p 8000:8000 nmo-service
```

容器起来后新旧接口都对外可用（无 Swagger/Redoc 页面，只走 HTTP JSON）：

| 接口 | 说明 |
| --- | --- |
| `POST /nmo/point` | 单炮检距走时、校正量、拉伸标记 |
| `POST /nmo/curve` | 炮检距网格上的整条双曲线 |
| `POST /nmo/scan` | 候选叠加速度扫描，返回最平速度 |
| `PUT/GET/DELETE /velocity-models/{name}`、`GET /velocity-models` | 层状速度模型增删查（返回各界面 t0/vrms） |
| `POST /ray/point` | 单炮检距精确射线走时 + 双曲近似 + 两者之差 |
| `POST /ray/curve` | 严格递增炮检距网格上的整条精确射线曲线 |
| `POST /velocity-models/profile` | 从模型某界面的 t0/vrms 直接生成一套动校档 |

动校档：`PUT/GET/DELETE /profiles/{name}`、`GET /profiles`。

本地直接跑：`uvicorn app.main:app --host 0.0.0.0 --port 8000`（Python 3.12）。

## 请求示例

基准算例 `t0=2 s, v=2000 m/s, x=1000 m`，期望 `t = sqrt(4.25) ≈ 2.0615528`：

```bash
curl -X POST localhost:8000/nmo/point -H 'Content-Type: application/json' \
  -d '{"t0":2.0,"velocity":2000,"offset":1000}'
```

整条曲线（网格必须非空、严格递增）：

```bash
curl -X POST localhost:8000/nmo/curve -H 'Content-Type: application/json' \
  -d '{"t0":0.5,"velocity":2000,"offsets":[0,200,1000,2000]}'
```

速度扫描（网格首端须为 0；观测用 `event_velocity` 合成或直接给 `observed_times`）：

```bash
curl -X POST localhost:8000/nmo/scan -H 'Content-Type: application/json' \
  -d '{"t0":2.0,"event_velocity":2200,
       "offsets":[0,500,1000,2000,2500],
       "velocities":[1800,2000,2200,2400,2800]}'
# best_velocity = 2200，best_flatness = 0
```

命名动校档：

```bash
curl -X PUT localhost:8000/profiles/A -H 'Content-Type: application/json' \
  -d '{"t0":2.0,"velocity":2000}'
curl -X POST localhost:8000/nmo/point -H 'Content-Type: application/json' \
  -d '{"profile":"A","offset":1000}'
curl -X POST localhost:8000/nmo/scan -H 'Content-Type: application/json' \
  -d '{"profile":"A","offsets":[0,500,1000],"velocities":[1800,2000,2200]}'
```

层状速度模型 + 精确射线 + 接回老接口：

```bash
# 1) 存两层模型（响应里直接带每个界面的垂直双程走时与均方根速度）
curl -X PUT localhost:8000/velocity-models/base -H 'Content-Type: application/json' \
  -d '{"layers":[{"thickness":1000,"velocity":2000},{"thickness":1000,"velocity":3000}]}'

# 2) 单炮检距精确射线（第二界面，x=1000 m；炮检距正负均可）
curl -X POST localhost:8000/ray/point -H 'Content-Type: application/json' \
  -d '{"model":"base","interface":1,"offset":1000}'
# ray_parameter、exact_traveltime、hyperbolic_traveltime、
# traveltime_difference、t0=5/3、vrms=sqrt(6000000)、recomputed_offset

# 3) 一排严格递增炮检距整条曲线
curl -X POST localhost:8000/ray/curve -H 'Content-Type: application/json' \
  -d '{"model":"base","interface":1,"offsets":[0,500,1000,3000,8000]}'

# 4) 从第二界面生成动校档，老接口直接用
curl -X POST localhost:8000/velocity-models/profile -H 'Content-Type: application/json' \
  -d '{"model":"base","interface":1,"profile_name":"event2"}'
curl -X POST localhost:8000/nmo/point -H 'Content-Type: application/json' \
  -d '{"profile":"event2","offset":1000}'
curl -X POST localhost:8000/nmo/scan -H 'Content-Type: application/json' \
  -d '{"profile":"event2","offsets":[0,500,1000],"velocities":[2000,2449.49,3000]}'
```

## 错误响应

所有不合法输入在计算启动前拦住，统一返回：

```json
{"error": true, "reason": "叠加速度 velocity 必须为正"}
```

涵盖：速度非正、`t0` 为负、非有限数值、炮检距网格为空/非严格递增（端点次序不对）、
候选速度列表为空、扫描网格首端非零偏移、档名与内联参数混用、动校档不存在（404）。
层状模型侧另涵盖：层数为空或超过 30、厚度/层速度非有限正数（含布尔值）、
界面编号越界、模型不存在（404）、生成档名为空。

## 代码结构

```
app/
  nmo.py            # 单点块：双曲线走时与校正量（唯一公式实现）
  stretch.py        # 拉伸标记判定，单列一块
  curve.py          # 曲线块：逐点调用单点内核铺整条双曲线
  scan.py           # 扫描块：候选速度逐个评估平整度
  profiles.py       # 动校档内存存取（独立名字空间）
  raytrace.py       # 层状模型、斯奈尔射线追踪与归一化射线参数求根（公式集中于此）
  velocity_models.py# 层状速度模型内存存取（独立名字空间，重启即丢）
  model_routes.py   # 模型/射线路由层：只解析请求、组织返回，不含公式
  model_schemas.py  # 模型/射线接口的请求与响应模型
  validation.py     # 参数校验（独立，计算前拦截；含层数/层值/界面编号校验）
  errors.py         # 带原因的领域错误
  schemas.py        # 动校三接口的请求/响应模型
  router.py         # 动校三接口路由层：只解析请求、组织返回
  main.py           # FastAPI 装配与错误响应映射
tests/              # pytest，动校核心关系 + 精确射线物理关系 + 基准算例回归
```

## 测试

```bash
pip install -r requirements-dev.txt
pytest
```

自动化测试逐条钉住：

1. 炮检距为零时校正量为零；
2. 炮检距绝对值翻倍，走时公式里的平方项变四倍（速度翻倍则变 1/4）；
3. 曲线在各炮检距处与单点接口同参结果完全一致；
4. 速度扫描中正确速度把双曲线拉得最平（平整度为 0）；
5. 基准算例 `sqrt(4.25)` 回归；
6. 非法输入提前拦截、拉伸只告警不拒绝、两档扫描互不串参、动校档重启即失。

层状模型 / 精确射线侧（`test_velocity_models.py`、`test_raytrace.py`、
`test_model_validation.py`、`test_profile_generation.py`）：

7. 只有一层时，任意炮检距精确走时与原 `/nmo/point` 在等效 `t0`、同一速度下
   的走时一致，误差 ≤ 1e-9 s（内核恒等，仅舍入级差异）；
8. 精确走时曲线在任一炮检距处对炮检距的斜率等于该点射线参数（中心差分，
   相对误差 ≤ 1e-6）；
9. 小偏移时差趋于零：炮检距减半后，精确与双曲之差至少缩小到 1/8（四次收敛）；
10. 炮检距取到界面深度 20 倍、层间速度差 5 倍以上仍收敛，复算炮检距与请求值
    之差 ≤ 1 mm；30 层模型大炮检距同样毫米级；
11. 两层基准模型第二界面 `t0=5/3 s`、`vrms=sqrt(6 000 000)≈2449.49 m/s`
    手算回归；
12. 界面编号越界、炮检距序列为空/次序不对、层数为空或超 30、厚度或速度不是
    有限正数（含布尔值），都在计算启动前带原因打回；
13. 曲线逐点与单点请求逐位一致；零炮检距 `p=0`；正负炮检距按绝对值处理；
14. 模型与动校档同名互不覆盖、各自重启即丢；从界面生成的档被原 point/curve/
    scan 接口正常使用。

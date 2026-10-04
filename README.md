# 反射双曲线动校正（NMO）核算服务

常驻 HTTP 服务，只做水平层状介质反射波正常时差这一件事。两套能力并列：

1. **单速度双曲动校正**：给定零偏移距双程走时 `t0`、叠加速度 `v`、炮检距 `x`，
   核算反射走时与动校正量、浅层大偏移拉伸告警，支持整条双曲线铺线与候选叠加速度扫描；
2. **层状速度模型 + 精确射线走时**：自上而下给出各层厚度与层速度，按斯奈尔定律
   追踪真实折射/反射射线路径，给出精确走时，并与“该界面 t0、均方根速度套双曲”的
   近似走时摆在一起，直接看出单速度双曲在远道的残差。

无网页、无工区管理、无测井台账。

## 内核公式

### 双曲动校正

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

### 层状模型派生量

第 k 个层底界面（界面编号自 1 起）：

```
depth_k = Σ_{i≤k} h_i
t0_k    = 2 Σ_{i≤k} h_i / v_i                    （垂直双程走时）
vrms_k² = (Σ_{i≤k} v_i h_i) / (Σ_{i≤k} h_i / v_i)   （均方根速度）
```

### 精确射线走时

射线从地表出发，在各层按斯奈尔定律折射、在目标界面反射后原路返回：

```
Snell:      p = sin θ_i / v_i                     （射线参数，全路径守恒）
水平投影:    X_i = p v_i h_i / sqrt(1 − (p v_i)²)  （单程）
层内时间:    τ_i = h_i / (v_i sqrt(1 − p² v_i²))   （单程）
炮检距:      x   = 2p Σ v_i h_i / sqrt(1 − (p v_i)²)
精确双程走时: t = 2 Σ h_i / (v_i sqrt(1 − p² v_i²))
```

给定炮检距，服务解出满足该炮检距的射线参数 p，再算精确走时；同时返回用
`t0_k、vrms_k` 套双曲得到的近似走时与两者之差（精确 − 双曲）。层状介质中该差
在远道为负：单速度双曲会把远道过校正，这正是上覆多层速度结构带来、换候选
速度消不掉的残差。

#### 射线参数怎么求：换变量 u，不直接对 p 开区间对分

p 的合法区间是 `[0, 1/v_max)`，右端是开的临界奇点。**直接对 p 求根的代价**：
逼近临界值时 `sqrt(1−(pv)²)` 因相消丢精度、`1/sqrt(…)` 发散溢出，右端点要
人为“留余量”，余量取多少没有统一答案。

服务改用

```
u = sqrt(1 − (p·v_max)²)，p = sqrt(1 − u²) / v_max，u ∈ (0, 1]
```

记 `r_i = v_i/v_max ≤ 1`、`q_i = (1−r_i)(1+r_i)`：

```
X(u) = Σ h_i r_i sqrt((1−u)(1+u)) / sqrt(q_i + r_i² u²)
t(u) = 2 Σ h_i / (v_i sqrt(q_i + r_i² u²))
```

- 全程没有开平方相消项（`1−u²`、`1−r_i²` 都用因式形式）；
- 最快层 r=1、q=0，分母直接就是 u，u→0 时是干净的 1/u 发散，不出 NaN/负数开根；
- X(u) 对 u 严格单调递减，括根只需从 u=1 起逐次对分（u→u/2），天然不越过
  u=0，不外推、不猜右端点，再做标准二分到机器精度。

**选择 u 的代价**：每点几十次 O(层数) 求和（30 层仍是瞬时），不引入任何外部
求解器；换来的是 p 逼近最快层临界值时不溢出、不跑飞。返回的射线参数仍按
物理量 p（s/m）报告，并附“用 p 复算的炮检距”供核对。

## 接口

容器起来后全部接口对外可用（无 Swagger/Redoc 页面，只走 HTTP JSON）：

| 接口 | 说明 |
| --- | --- |
| `POST /nmo/point` | 单炮检距双曲走时、校正量、拉伸标记 |
| `POST /nmo/curve` | 炮检距网格上的整条双曲线 |
| `POST /nmo/scan` | 候选叠加速度扫描，返回最平速度 |
| `PUT/GET/DELETE /models/{name}`、`GET /models` | 层状模型增删查（GET 响应内含每个层底界面的 t0 与 vrms） |
| `POST /models/{name}/interfaces/{k}/ray/point` | 单点精确射线走时 + 双曲近似 + 两者之差 |
| `POST /models/{name}/interfaces/{k}/ray/curve` | 一排严格递增炮检距的精确射线曲线 |
| `POST /models/{name}/interfaces/{k}/profile` | 用第 k 界面的 t0、vrms 直接生成一套动校档 |
| `PUT/GET/DELETE /profiles/{name}`、`GET /profiles` | 动校档增删查（原有行为不变） |

两类命名存储都是**纯内存、重启即丢**，但**各管各的名字**：同名模型与动校档
互不覆盖、互不可见。生成的动校档落在动校档命名空间（默认档名取模型名），
之后原有的单点、曲线、速度扫描接口拿档名照常使用。

## 镜像构建与运行（一键）

```bash
docker build -t nmo-service .
docker run --rm -p 8000:8000 nmo-service
```

本地直接跑：`uvicorn app.main:app --host 0.0.0.0 --port 8000`（Python 3.12）。

## 请求示例

双曲基准算例 `t0=2 s, v=2000 m/s, x=1000 m`，期望 `t = sqrt(4.25) ≈ 2.0615528`：

```bash
curl -X POST localhost:8000/nmo/point -H 'Content-Type: application/json' \
  -d '{"t0":2.0,"velocity":2000,"offset":1000}'
```

两层基准模型（h₁=1000 m、v₁=2000 m/s；h₂=1000 m、v₂=3000 m/s）：

```bash
curl -X PUT localhost:8000/models/base -H 'Content-Type: application/json' \
  -d '{"layers":[{"thickness":1000,"velocity":2000},{"thickness":1000,"velocity":3000}]}'
# 第二界面: t0 = 5/3 s, vrms = sqrt(6000000) ≈ 2449.49 m/s

curl -X POST localhost:8000/models/base/interfaces/2/ray/point \
  -H 'Content-Type: application/json' \
  -d '{"model":"base","interface":2,"offset":2000}'
# ray_parameter 精确射参数；exact_time 精确走时；hyperbolic_time 双曲近似；
# difference = exact_time − hyperbolic_time；recomputed_offset 用 p 复算的炮检距

curl -X POST localhost:8000/models/base/interfaces/2/ray/curve \
  -H 'Content-Type: application/json' \
  -d '{"model":"base","interface":2,"offsets":[0,500,1000,2000,5000]}'

# 用第二界面直接生成动校档，老接口照常可用
curl -X POST localhost:8000/models/base/interfaces/2/profile \
  -H 'Content-Type: application/json' -d '{"profile":"if2"}'
curl -X POST localhost:8000/nmo/point -H 'Content-Type: application/json' \
  -d '{"profile":"if2","offset":2000}'
```

炮检距正负均可，按绝对值处理；为零时射线参数为零，精确走时就是垂直双程走时。
曲线网格必须非空、严格递增，逐点结果与相同输入的单点请求完全一致。

## 错误响应

所有不合法输入在计算启动前拦住，统一返回：

```json
{"error": true, "reason": "叠加速度 velocity 必须为正"}
```

原有口径：速度非正、`t0` 为负、非有限数值、炮检距网格为空/非严格递增、
候选速度列表为空、扫描网格首端非零偏移、档名与内联参数混用、资源不存在（404）。

新增口径：目标界面编号越界（非正整数或超过层数）、层数越界（空列表或超过 30
层）、层厚或层速度不是有限正数、层字段缺失/形状不对、射线请求炮检距非有限值、
路径模型名与请求体不一致、层状模型不存在（404）。

## 代码结构

```
app/
  nmo.py         # 单点块：双曲走时与校正量（唯一双曲公式实现）
  stretch.py     # 拉伸标记判定，单列一块
  curve.py       # 双曲曲线块：逐点调用单点内核
  scan.py        # 扫描块：候选速度逐个评估平整度
  layers.py      # 层状模型：结构、垂直双程走时、均方根速度（唯一派生量实现）
  rays.py        # 精确射线块：u 变量对分求射线参数、精确/双曲走时与残差
  profiles.py    # 动校档内存存取
  model_store.py # 层状模型内存存取（独立命名空间）
  validation.py  # 参数校验（独立，计算前拦截）
  errors.py      # 带原因的领域错误
  schemas.py     # 请求/响应模型
  router.py      # 原双曲三接口与动校档路由：只解析与组织返回
  models_router.py # 模型、精确射线、界面生动校档路由：同样不含公式
  main.py        # FastAPI 装配与错误响应映射
tests/           # pytest，含双曲核心关系与层状射线全部核对关系
```

## 测试

```bash
pip install -r requirements-dev.txt
pytest
```

自动化测试在原有六条之外，逐条钉住：

1. 只有一层时，任意炮检距的精确走时与原单点接口在等效 t0、同速度下的结果
   一致（≤ 1e-9 s）；
2. 精确走时曲线在任一炮检距处对 x 的斜率等于该点射线参数（小步长中心差分，
   相对误差 ≤ 1e-6）；
3. 小偏移时精确与双曲之差趋于零，炮检距减半后该差至少缩小到 1/8；
4. 炮检距取到界面深度 20 倍、层间速度比 5 倍以上仍收敛，复算炮检距与请求值
   之差 ≤ 1 mm；
5. 两层基准模型第二界面 `t0 = 5/3 s`、`vrms = sqrt(6e6) ≈ 2449.49 m/s`，
   手算值回归；
6. 界面编号越界、炮检距序列为空或次序不对、层数越界、层厚/速度非有限正数，
   全部在计算启动前带原因打回；
7. 模型与动校档同名互不覆盖；从界面生成的动校档被原单点、曲线、扫描接口
   正常使用（扫描以 vrms 为最平速度）；两类存储重启即丢。

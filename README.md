# 反射双曲线动校正（NMO）核算服务

常驻 HTTP 服务，只做水平层状介质反射波正常时差这一件事：给定零偏移距双程走时
`t0`、叠加速度 `v`、炮检距 `x`，核算反射走时与动校正量、浅层大偏移拉伸告警，
并支持整条双曲线铺线与候选叠加速度扫描。无网页、无工区管理、无测井台账。

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

## 镜像构建与运行（一键）

```bash
docker build -t nmo-service .
docker run --rm -p 8000:8000 nmo-service
```

容器起来后三个接口对外可用（无 Swagger/Redoc 页面，只走 HTTP JSON）：

| 接口 | 说明 |
| --- | --- |
| `POST /nmo/point` | 单炮检距走时、校正量、拉伸标记 |
| `POST /nmo/curve` | 炮检距网格上的整条双曲线 |
| `POST /nmo/scan` | 候选叠加速度扫描，返回最平速度 |

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

## 错误响应

所有不合法输入在计算启动前拦住，统一返回：

```json
{"error": true, "reason": "叠加速度 velocity 必须为正"}
```

涵盖：速度非正、`t0` 为负、非有限数值、炮检距网格为空/非严格递增（端点次序不对）、
候选速度列表为空、扫描网格首端非零偏移、档名与内联参数混用、动校档不存在（404）。

## 代码结构

```
app/
  nmo.py        # 单点块：双曲线走时与校正量（唯一公式实现）
  stretch.py    # 拉伸标记判定，单列一块
  curve.py      # 曲线块：逐点调用单点内核铺整条双曲线
  scan.py       # 扫描块：候选速度逐个评估平整度
  profiles.py   # 动校档内存存取（独立）
  validation.py # 参数校验（独立，计算前拦截）
  errors.py     # 带原因的领域错误
  schemas.py    # 请求/响应模型
  router.py     # 路由层：只解析请求、组织三个接口返回
  main.py       # FastAPI 装配与错误响应映射
tests/          # pytest，含三条核心关系与基准算例回归
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

import {
  Activity,
  Archive,
  BookOpen,
  Bot,
  Check,
  ChevronRight,
  CircleDot,
  Download,
  GitCompare,
  LayoutDashboard,
  Library,
  LogOut,
  Menu,
  Network,
  PenLine,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  WalletCards,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, authSession } from './api'
import type {
  AgentRun,
  AuthUser,
  Draft,
  MemoryHit,
  PlotPlan,
  Project,
  StoryBible,
  Workflow,
  WorkflowDetail,
} from './types'

type Tab = 'overview' | 'bible' | 'plot' | 'workflows' | 'drafts' | 'memory'

const navItems: Array<{ id: Tab; label: string; icon: typeof BookOpen }> = [
  { id: 'overview', label: '项目概览', icon: LayoutDashboard },
  { id: 'bible', label: '故事圣经', icon: Library },
  { id: 'plot', label: '剧情规划', icon: Network },
  { id: 'workflows', label: '审批队列', icon: CircleDot },
  { id: 'drafts', label: '章节草稿', icon: PenLine },
  { id: 'memory', label: '长期记忆', icon: Archive },
]

const statusLabels: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  waiting_approval: '待审批',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  draft: '草稿',
  accepted: '已接受',
  rejected: '已拒绝',
  superseded: '已迭代',
}

function App() {
  const [user, setUser] = useState<AuthUser>()
  const [checking, setChecking] = useState(authSession.hasToken())

  useEffect(() => {
    const expire = () => setUser(undefined)
    window.addEventListener('auth-expired', expire)
    if (authSession.hasToken()) {
      api.me()
        .then((result) => setUser(result.user))
        .catch(() => authSession.clear())
        .finally(() => setChecking(false))
    }
    return () => window.removeEventListener('auth-expired', expire)
  }, [])

  if (checking) {
    return (
      <div className="center-screen">
        <div className="ink-loader" />
        <span>正在验证登录状态…</span>
      </div>
    )
  }

  if (!user) {
    return <AuthScreen onAuthenticated={setUser} />
  }

  return <Workspace user={user} onLogout={() => {
    authSession.clear()
    setUser(undefined)
  }} />
}

function Workspace({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [tab, setTab] = useState<Tab>('overview')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [balance, setBalance] = useState<number>()

  const loadProjects = useCallback(async () => {
    try {
      const result = await api.projects()
      setProjects(result)
      setProjectId((current) => current || result[0]?.id || '')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法读取项目')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadProjects()
    api.balance().then((result) => setBalance(result.balance)).catch(() => undefined)
  }, [loadProjects])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 2800)
    return () => window.clearTimeout(timer)
  }, [notice])

  const project = projects.find((item) => item.id === projectId)
  const feedback = useCallback((message: string) => {
    setNotice(message)
    setError('')
  }, [])
  const fail = useCallback(
    (reason: unknown) => setError(reason instanceof Error ? reason.message : '操作失败'),
    [],
  )

  if (loading) {
    return (
      <div className="center-screen">
        <div className="ink-loader" />
        <span>正在展开稿纸…</span>
      </div>
    )
  }

  if (!projects.length) {
    return <>
      <button className="onboarding-logout secondary" onClick={onLogout}>
        <LogOut size={15} />退出登录
      </button>
      <ProjectOnboarding onCreated={(created) => {
        setProjects([created])
        setProjectId(created.id)
      }} />
    </>
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">砚</div>
          <div>
            <strong>砚台</strong>
            <span>Novel Harness</span>
          </div>
          <button className="icon-button mobile-close" onClick={() => setMobileOpen(false)}>
            <X size={18} />
          </button>
        </div>

        <label className="project-picker">
          <span>当前作品</span>
          <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
            {projects.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </label>

        <nav>
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <button
                key={item.id}
                className={tab === item.id ? 'active' : ''}
                onClick={() => {
                  setTab(item.id)
                  setMobileOpen(false)
                }}
              >
                <Icon size={18} strokeWidth={1.8} />
                {item.label}
              </button>
            )
          })}
        </nav>

        <div className="sidebar-note">
          <Sparkles size={17} />
          <div>
            <strong>Canon 安全模式</strong>
            <span>草稿经作者接受后才更新设定</span>
          </div>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <button className="icon-button menu-button" onClick={() => setMobileOpen(true)}>
            <Menu size={20} />
          </button>
          <div>
            <span className="eyebrow">{project?.genre} · {project?.sub_genre || '未设置子类型'}</span>
            <h1>{navItems.find((item) => item.id === tab)?.label}</h1>
          </div>
          <div className="topbar-meta">
            <WalletCards size={15} />
            <span>¥{balance?.toFixed(2) ?? '—'}</span>
            <strong>{user.nickname || user.email || user.phone}</strong>
            <button className="icon-button" title="退出登录" onClick={onLogout}>
              <LogOut size={16} />
            </button>
          </div>
        </header>

        <div className="workspace">
          {tab === 'overview' && project && (
            <Overview project={project} onNavigate={setTab} fail={fail} />
          )}
          {tab === 'bible' && project && (
            <BibleWorkspace project={project} feedback={feedback} fail={fail} />
          )}
          {tab === 'plot' && project && (
            <PlotWorkspace project={project} feedback={feedback} fail={fail} />
          )}
          {tab === 'workflows' && project && (
            <WorkflowWorkspace project={project} feedback={feedback} fail={fail} />
          )}
          {tab === 'drafts' && project && (
            <DraftWorkspace project={project} feedback={feedback} fail={fail} />
          )}
          {tab === 'memory' && project && (
            <MemoryWorkspace project={project} fail={fail} />
          )}
        </div>
      </main>

      {mobileOpen && <button className="scrim" onClick={() => setMobileOpen(false)} />}
      {error && <Toast kind="error" message={error} onClose={() => setError('')} />}
      {notice && <Toast kind="success" message={notice} onClose={() => setNotice('')} />}
    </div>
  )
}

function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [method, setMethod] = useState<'email' | 'phone'>('email')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const submit = async () => {
    if (!login.trim() || !password) return
    setBusy(true)
    setError('')
    try {
      if (mode === 'register') {
        await api.register(method, login.trim(), password, code)
      }
      const result = await api.login(login.trim(), password)
      authSession.setToken(result.token)
      onAuthenticated(result.user)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '认证失败')
    } finally {
      setBusy(false)
    }
  }

  const sendCode = async () => {
    if (!login.trim()) return
    setBusy(true)
    setError('')
    try {
      const result = await api.sendRegisterCode(method, login.trim())
      setMessage(result.message)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '验证码发送失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="onboarding auth-page">
      <div className="onboarding-copy">
        <div className="brand-mark large">砚</div>
        <span className="eyebrow">Novel Harness</span>
        <h1>每一部作品，都只属于它的作者。</h1>
        <p>登录后，作品、长期记忆与生成用量会按账户独立保存和计费。</p>
      </div>
      <div className="onboarding-card auth-card">
        <div className="auth-tabs">
          <button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>
            登录
          </button>
          <button className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>
            注册
          </button>
        </div>
        {mode === 'register' && (
          <div className="contact-tabs">
            <button className={method === 'email' ? 'active' : ''} onClick={() => setMethod('email')}>
              邮箱
            </button>
            <button className={method === 'phone' ? 'active' : ''} onClick={() => setMethod('phone')}>
              手机号
            </button>
          </div>
        )}
        <Field
          label={mode === 'login' ? '邮箱或手机号' : method === 'email' ? '邮箱' : '手机号'}
          value={login}
          onChange={setLogin}
          placeholder={method === 'email' ? 'author@example.com' : '13800000000'}
        />
        <Field
          label="密码"
          value={password}
          onChange={setPassword}
          placeholder="至少 6 位"
          type="password"
        />
        {mode === 'register' && (
          <div className="verification-row">
            <Field label="验证码" value={code} onChange={setCode} placeholder="6 位验证码" />
            <button className="secondary" disabled={busy || !login} onClick={() => void sendCode()}>
              发送验证码
            </button>
          </div>
        )}
        {message && <p className="form-notice">{message}</p>}
        {error && <p className="form-error">{error}</p>}
        <button
          className="primary wide"
          disabled={busy || !login || !password || (mode === 'register' && code.length !== 6)}
          onClick={() => void submit()}
        >
          {busy ? '处理中…' : mode === 'login' ? '进入工作台' : '注册并登录'}
          <ChevronRight size={17} />
        </button>
      </div>
    </div>
  )
}

function ProjectOnboarding({ onCreated }: { onCreated: (project: Project) => void }) {
  const [name, setName] = useState('')
  const [genre, setGenre] = useState('历史')
  const [premise, setPremise] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const create = async () => {
    if (!name.trim()) return
    setBusy(true)
    try {
      onCreated(await api.createProject({ name, genre, premise }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '创建失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="onboarding">
      <div className="onboarding-copy">
        <div className="brand-mark large">砚</div>
        <span className="eyebrow">Novel Agent Harness</span>
        <h1>让长篇故事，始终记得自己从哪里来。</h1>
        <p>从一页设定开始，建立可追溯、可修订、不会擅自改写的创作工作流。</p>
      </div>
      <div className="onboarding-card">
        <h2>创建第一部作品</h2>
        <Field label="作品名" value={name} onChange={setName} placeholder="例如：长安旧梦" />
        <Field label="类型" value={genre} onChange={setGenre} placeholder="历史、玄幻、都市…" />
        <Field
          label="一句话梗概"
          value={premise}
          onChange={setPremise}
          placeholder="主角是谁，他必须完成什么？"
          multiline
        />
        {error && <p className="form-error">{error}</p>}
        <button className="primary wide" onClick={() => void create()} disabled={busy || !name}>
          {busy ? '创建中…' : '进入工作台'} <ChevronRight size={17} />
        </button>
      </div>
    </div>
  )
}

function Overview({
  project,
  onNavigate,
  fail,
}: {
  project: Project
  onNavigate: (tab: Tab) => void
  fail: (reason: unknown) => void
}) {
  const [bible, setBible] = useState<StoryBible>()
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [runs, setRuns] = useState<AgentRun[]>([])

  useEffect(() => {
    Promise.all([
      api.bible(project.id),
      api.drafts(project.id),
      api.workflows(project.id),
      api.agentRuns(project.id),
    ]).then(([nextBible, nextDrafts, nextWorkflows, nextRuns]) => {
      setBible(nextBible)
      setDrafts(nextDrafts)
      setWorkflows(nextWorkflows)
      setRuns(nextRuns)
    }).catch(fail)
  }, [project.id, fail])

  const latestRun = runs.at(-1)
  return (
    <div className="page-stack">
      <section className="hero-card">
        <div>
          <span className="eyebrow">正在创作</span>
          <h2>{project.name}</h2>
          <p>{project.premise || '尚未填写故事梗概。先完善世界与人物，再开始第一章。'}</p>
        </div>
        <button className="primary" onClick={() => onNavigate('plot')}>
          <Sparkles size={17} /> 规划下一章
        </button>
      </section>

      <section className="metric-grid">
        <Metric label="Canon 版本" value={`v${bible?.version || 1}`} note={`${bible?.characters.length || 0} 位人物`} />
        <Metric label="章节草稿" value={String(drafts.length)} note={`${drafts.filter((item) => item.status === 'accepted').length} 篇已接受`} />
        <Metric label="待审批" value={String(workflows.filter((item) => item.status === 'waiting_approval').length)} note="需要作者决定" />
        <Metric label="Agent 调用" value={String(runs.length)} note={latestRun ? `${latestRun.agent_name} · ${latestRun.duration_ms || 0}ms` : '尚无调用'} />
      </section>

      <section className="two-column">
        <Panel title="创作路径" action={<button className="text-button" onClick={() => onNavigate('workflows')}>查看队列</button>}>
          <div className="journey">
            {['资料与设定', '剧情选择', '章节写作', '审校修订', '接受 Canon'].map((label, index) => (
              <div key={label} className={index === 0 ? 'done' : ''}>
                <span>{index === 0 ? <Check size={14} /> : index + 1}</span>
                <strong>{label}</strong>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="最近运行">
          <div className="run-list compact">
            {runs.slice(-5).reverse().map((run) => <RunRow key={run.id} run={run} />)}
            {!runs.length && <Empty text="生成剧情或分析设定后，这里会显示运行记录。" />}
          </div>
        </Panel>
      </section>
    </div>
  )
}

function BibleWorkspace({
  project,
  feedback,
  fail,
}: {
  project: Project
  feedback: (message: string) => void
  fail: (reason: unknown) => void
}) {
  const [bible, setBible] = useState<StoryBible>()
  const [mode, setMode] = useState<'character' | 'world' | 'foreshadowing' | 'entry'>('character')
  const [name, setName] = useState('')
  const [role, setRole] = useState('')
  const [brief, setBrief] = useState('')
  const [goal, setGoal] = useState('')
  const [entryKind, setEntryKind] = useState<'rules' | 'factions' | 'locations' | 'timeline'>('rules')
  const [entry, setEntry] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => api.bible(project.id).then(setBible).catch(fail), [project.id, fail])
  useEffect(() => { void refresh() }, [refresh])

  const runAgent = async () => {
    if (!bible) return
    setBusy(true)
    try {
      if (mode === 'character') {
        const result = await api.proposeCharacter(project.id, { name, role, brief, apply: true })
        if (result.bible) setBible(result.bible)
        setName(''); setRole(''); setBrief('')
        feedback('人物提案已确认并写入 Story Bible')
      } else if (mode === 'world') {
        const result = await api.proposeWorld(project.id, goal, true)
        if (result.bible) setBible(result.bible)
        setGoal('')
        feedback('世界观提案已写入 Story Bible')
      } else if (mode === 'foreshadowing') {
        const result = await api.proposeForeshadowing(project.id, goal, true)
        if (result.bible) setBible(result.bible)
        setGoal('')
        feedback('伏笔方案已加入待埋设列表')
      } else {
        const value = entryKind === 'rules' ? entry : JSON.parse(entry)
        setBible(
          entryKind === 'timeline'
            ? await api.addTimeline(project.id, value, bible.version)
            : await api.addBibleEntry(project.id, entryKind, value, bible.version),
        )
        setEntry('')
        feedback('设定条目已保存')
      }
    } catch (reason) {
      fail(reason)
    } finally {
      setBusy(false)
    }
  }

  if (!bible) return <LoadingBlock />
  return (
    <div className="page-stack">
      <section className="section-heading">
        <div>
          <span className="eyebrow">Story Bible · v{bible.version}</span>
          <h2>故事的确定事实</h2>
          <p>每次更新都会生成不可变版本；Agent 提案只有经你确认才会进入 Canon。</p>
        </div>
        <button className="secondary" onClick={() => void refresh()}><RefreshCw size={16} />刷新</button>
      </section>

      <section className="two-column bible-layout">
        <div className="page-stack">
          <Panel title="世界摘要">
            <p className="prose">{bible.world_summary || '还没有世界摘要。使用世界观 Agent 建立第一版规则。'}</p>
          </Panel>
          <Panel title={`人物 · ${bible.characters.length}`}>
            <div className="entity-grid">
              {bible.characters.map((character) => (
                <article className="entity-card" key={character.id}>
                  <div className="avatar">{character.name.slice(0, 1)}</div>
                  <div><strong>{character.name}</strong><span>{character.role || '未指定角色'}</span></div>
                  <p>{character.motivation || '动机待完善'}</p>
                </article>
              ))}
              {!bible.characters.length && <Empty text="尚无人物。右侧可生成并确认人物提案。" />}
            </div>
          </Panel>
          <div className="three-column">
            <EntryPanel title="世界规则" entries={bible.rules} />
            <EntryPanel title="势力" entries={bible.factions} />
            <EntryPanel title="地点" entries={bible.locations} />
          </div>
          <Panel title={`时间线 · ${bible.timeline.length}`}>
            <ul className="entry-list">
              {bible.timeline.map((item, index) => (
                <li key={String(item.id || index)}>
                  {String(item.time_reference || item.label || `事件 ${index + 1}`)} · {String(item.summary || '')}
                </li>
              ))}
              {!bible.timeline.length && <li className="muted">尚未记录时间线事件</li>}
            </ul>
          </Panel>
          <Panel title={`伏笔与悬念 · ${bible.foreshadowing_items.length}`}>
            <div className="thread-list">
              {bible.foreshadowing_items.map((item) => (
                <div key={item.id}>
                  <span className={`status ${item.status}`}>{item.status}</span>
                  <div><strong>{item.description}</strong><p>{item.expected_payoff || '回收目标待定'}</p></div>
                  {item.status !== 'resolved' && (
                    <button className="text-button" onClick={async () => {
                      const resolution = window.prompt('如何回收这条伏笔？')
                      if (!resolution) return
                      try {
                        setBible(await api.resolveForeshadowing(project.id, item.id, resolution, bible.version))
                        feedback('伏笔已回收')
                      } catch (reason) { fail(reason) }
                    }}>标记回收</button>
                  )}
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <aside className="composer-card sticky">
          <span className="eyebrow">智能设定助手</span>
          <h3>提出建议，由你定稿</h3>
          <div className="segmented">
            {[
              ['character', '人物'],
              ['world', '世界'],
              ['foreshadowing', '伏笔'],
              ['entry', '手动'],
            ].map(([id, label]) => (
              <button key={id} className={mode === id ? 'active' : ''} onClick={() => setMode(id as typeof mode)}>{label}</button>
            ))}
          </div>
          {mode === 'character' && <>
            <Field label="姓名" value={name} onChange={setName} placeholder="人物姓名" />
            <Field label="角色定位" value={role} onChange={setRole} placeholder="主角、盟友、对手…" />
            <Field label="人物简述" value={brief} onChange={setBrief} placeholder="背景、目标或特殊约束" multiline />
          </>}
          {(mode === 'world' || mode === 'foreshadowing') && (
            <Field
              label={mode === 'world' ? '本次完善目标' : '场景目标'}
              value={goal}
              onChange={setGoal}
              placeholder={mode === 'world' ? '完善长安城内的权力结构' : '主角首次进入未央宫'}
              multiline
            />
          )}
          {mode === 'entry' && <>
            <label className="field"><span>条目类型</span><select value={entryKind} onChange={(e) => setEntryKind(e.target.value as typeof entryKind)}><option value="rules">规则</option><option value="factions">势力（JSON）</option><option value="locations">地点（JSON）</option><option value="timeline">时间线（JSON）</option></select></label>
            <Field label="内容" value={entry} onChange={setEntry} placeholder={entryKind === 'rules' ? '规则文本' : entryKind === 'timeline' ? '{"sequence":1,"summary":"事件摘要"}' : '{"name":"名称","goal":"目标"}'} multiline />
          </>}
          <button className="primary wide" onClick={() => void runAgent()} disabled={busy}>
            {busy ? '正在推演…' : mode === 'entry' ? '保存条目' : '生成并确认'} <Sparkles size={16} />
          </button>
        </aside>
      </section>
    </div>
  )
}

function PlotWorkspace({
  project,
  feedback,
  fail,
}: {
  project: Project
  feedback: (message: string) => void
  fail: (reason: unknown) => void
}) {
  const [current, setCurrent] = useState('')
  const [goal, setGoal] = useState('')
  const [plan, setPlan] = useState<PlotPlan>()
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)

  const generate = async () => {
    setBusy(true)
    try {
      const result = await api.plan(project.id, current, goal)
      setPlan(result)
      setSelected('')
    } catch (reason) { fail(reason) } finally { setBusy(false) }
  }
  const choose = async (optionId: string) => {
    if (!plan) return
    try {
      setPlan(await api.selectPlan(project.id, plan.id, optionId))
      setSelected(optionId)
      feedback('剧情方案已锁定')
    } catch (reason) { fail(reason) }
  }
  const write = async () => {
    if (!plan || !selected) return
    setBusy(true)
    try {
      await api.write(project.id, {
        goal,
        current,
        plot_plan_id: plan.id,
        selected_option_id: selected,
      })
      feedback('章节草稿已生成，可前往“章节草稿”审阅')
    } catch (reason) { fail(reason) } finally { setBusy(false) }
  }

  return (
    <div className="page-stack">
      <section className="section-heading">
        <div><span className="eyebrow">Plot Studio</span><h2>把选择权留给作者</h2><p>先生成三条可比较的路线，确认一条后再进入正文写作。</p></div>
      </section>
      <Panel title="本章意图">
        <div className="form-row">
          <Field label="当前剧情" value={current} onChange={setCurrent} placeholder="主角抵达长安城外，身份文书存疑" multiline />
          <Field label="作者目标" value={goal} onChange={setGoal} placeholder="主角通过城门，并第一次看见长安" multiline />
        </div>
        <button className="primary" disabled={!current || !goal || busy} onClick={() => void generate()}>
          <Sparkles size={17} /> {busy ? '正在规划…' : '生成剧情候选'}
        </button>
      </Panel>
      {plan && (
        <>
          <div className="plot-grid">
            {plan.next_chapter_options.map((option, index) => (
              <article key={option.id} className={`plot-card ${selected === option.id ? 'selected' : ''}`}>
                <div className="plot-index">方案 {['一', '二', '三'][index] || index + 1}</div>
                <h3>{option.title}</h3>
                <p>{option.summary}</p>
                <dl><dt>核心冲突</dt><dd>{option.conflict}</dd><dt>情绪兑现</dt><dd>{option.payoff}</dd></dl>
                {!!option.risks.length && <div className="risk-note"><strong>风险</strong>{option.risks.join('；')}</div>}
                <button className={selected === option.id ? 'selected-button' : 'secondary wide'} onClick={() => void choose(option.id)}>
                  {selected === option.id ? <><Check size={16} /> 已选择</> : '采用此方案'}
                </button>
              </article>
            ))}
          </div>
          <div className="action-bar">
            <div><strong>{selected ? '方案已确认' : '请选择一条剧情路线'}</strong><span>写作 Agent 只会执行你选定的方案</span></div>
            <button className="primary" disabled={!selected || busy} onClick={() => void write()}><PenLine size={17} />生成章节</button>
          </div>
        </>
      )}
    </div>
  )
}

function WorkflowWorkspace({
  project,
  feedback,
  fail,
}: {
  project: Project
  feedback: (message: string) => void
  fail: (reason: unknown) => void
}) {
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [detail, setDetail] = useState<WorkflowDetail>()
  const [approvalOption, setApprovalOption] = useState('')
  const [goal, setGoal] = useState('')
  const [current, setCurrent] = useState('')

  const refresh = useCallback(async (selectedId?: string) => {
    try {
      const items = await api.workflows(project.id)
      setWorkflows(items)
      const selected = selectedId || items.find((item) => item.status === 'waiting_approval')?.id || items.at(-1)?.id
      if (selected) setDetail(await api.workflow(selected))
    } catch (reason) { fail(reason) }
  }, [project.id, fail])

  useEffect(() => {
    api.workflows(project.id).then(async (items) => {
      setWorkflows(items)
      const selected = items.find((item) => item.status === 'waiting_approval')?.id || items.at(-1)?.id
      if (selected) setDetail(await api.workflow(selected))
    }).catch(fail)
  }, [project.id, fail])

  const approve = async () => {
    if (!detail?.run.current_step) return
    let optionId: string | undefined
    if (detail.run.current_step === 'plot_approval') {
      const planResult = detail.run.result.plan as { options?: Array<{ id: string; title: string }> } | undefined
      const options = planResult?.options || []
      optionId = approvalOption || options[0]?.id
      if (options.length && !optionId) return
    }
    try {
      setDetail(await api.approveWorkflow(detail.run.id, detail.run.current_step, optionId))
      feedback('审批决定已提交')
      await refresh(detail.run.id)
    } catch (reason) { fail(reason) }
  }

  return (
    <div className="page-stack">
      <section className="section-heading">
        <div><span className="eyebrow">Human in the loop</span><h2>审批队列</h2><p>研究、剧情和草稿都可以在关键节点暂停，等待你的判断。</p></div>
        <button className="secondary" onClick={() => void refresh()}><RefreshCw size={16} />刷新</button>
      </section>
      <section className="two-column workflow-layout">
        <Panel title="工作流">
          <div className="workflow-list">
            {workflows.slice().reverse().map((run) => (
              <button key={run.id} className={detail?.run.id === run.id ? 'active' : ''} onClick={() => api.workflow(run.id).then(setDetail).catch(fail)}>
                <span className={`status ${run.status}`}>{statusLabels[run.status] || run.status}</span>
                <strong>{String(run.parameters.goal || '章节工作流')}</strong>
                <small>{new Date(run.created_at).toLocaleString()}</small>
              </button>
            ))}
            {!workflows.length && <Empty text="暂无工作流。可在右侧创建。" />}
          </div>
        </Panel>
        <div className="page-stack">
          <Panel title="发起章节工作流">
            <Field label="当前剧情" value={current} onChange={setCurrent} placeholder="当前章节停在哪里？" />
            <Field label="章节目标" value={goal} onChange={setGoal} placeholder="这一章必须完成什么？" />
            <button className="primary" disabled={!goal} onClick={async () => {
              try {
                const created = await api.startWorkflow(project.id, goal, current)
                setDetail(created); setGoal(''); setCurrent('')
                feedback('工作流已进入队列')
                await refresh(created.run.id)
              } catch (reason) { fail(reason) }
            }}><Send size={16} />发起工作流</button>
          </Panel>
          {detail && (
            <Panel title={`运行详情 · ${statusLabels[detail.run.status] || detail.run.status}`}>
              <div className="stepper">
                {detail.steps.map((step) => (
                  <div key={step.id} className={step.status}>
                    <span>{step.status === 'succeeded' ? <Check size={14} /> : ''}</span>
                    <strong>{step.name.replaceAll('_', ' ')}</strong>
                    <small>{statusLabels[step.status] || step.status}</small>
                  </div>
                ))}
              </div>
              {detail.run.status === 'waiting_approval' && detail.run.current_step && (
                <div className="approval-box">
                  <div><strong>等待你的决定</strong><p>当前节点：{detail.run.current_step}</p></div>
                  {detail.run.current_step === 'plot_approval' && (() => {
                    const result = detail.run.result.plan as {
                      options?: Array<{ id: string; title: string }>
                    } | undefined
                    const options = result?.options || []
                    return options.length ? (
                      <select
                        aria-label="选择剧情方案"
                        value={approvalOption || options[0]?.id}
                        onChange={(event) => setApprovalOption(event.target.value)}
                      >
                        {options.map((option) => (
                          <option key={option.id} value={option.id}>{option.title}</option>
                        ))}
                      </select>
                    ) : null
                  })()}
                  <button className="danger-ghost" onClick={async () => {
                    const note = window.prompt('拒绝原因')
                    if (!note) return
                    try {
                      setDetail(await api.rejectWorkflow(detail.run.id, detail.run.current_step!, note))
                      feedback('已拒绝该节点')
                    } catch (reason) { fail(reason) }
                  }}>拒绝</button>
                  <button className="primary" onClick={() => void approve()}><Check size={16} />批准</button>
                </div>
              )}
            </Panel>
          )}
        </div>
      </section>
    </div>
  )
}

function DraftWorkspace({
  project,
  feedback,
  fail,
}: {
  project: Project
  feedback: (message: string) => void
  fail: (reason: unknown) => void
}) {
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [draft, setDraft] = useState<Draft>()
  const [instruction, setInstruction] = useState('')
  const [diff, setDiff] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async (selectedId?: string) => {
    try {
      const items = await api.drafts(project.id)
      setDrafts(items)
      const id = selectedId || items[0]?.id
      if (id) setDraft(await api.draft(id))
    } catch (reason) { fail(reason) }
  }, [project.id, fail])
  useEffect(() => {
    api.drafts(project.id).then(async (items) => {
      setDrafts(items)
      if (items[0]?.id) setDraft(await api.draft(items[0].id))
    }).catch(fail)
  }, [project.id, fail])

  const select = async (id: string) => {
    try { setDraft(await api.draft(id)); setDiff('') } catch (reason) { fail(reason) }
  }
  const revise = async () => {
    if (!draft || !instruction) return
    setBusy(true)
    try {
      const result = await api.reviseDraft(draft.id, instruction)
      setDraft(result.draft); setInstruction('')
      feedback('新修订版本已生成，原稿保留用于对比')
      await refresh(result.draft.id)
    } catch (reason) { fail(reason) } finally { setBusy(false) }
  }

  return (
    <div className="page-stack">
      <section className="section-heading">
        <div><span className="eyebrow">Draft room</span><h2>章节草稿与版本</h2><p>审阅正文、给出修订意见、比较版本，最终由你决定是否进入 Canon。</p></div>
      </section>
      <section className="draft-layout">
        <aside className="draft-list">
          {drafts.map((item) => (
            <button key={item.id} className={draft?.id === item.id ? 'active' : ''} onClick={() => void select(item.id)}>
              <div><strong>第 {item.revision_number} 版</strong><span className={`status ${item.status}`}>{statusLabels[item.status]}</span></div>
              <p>{item.creative_notes || '章节草稿'}</p>
              <small>{new Date(item.created_at).toLocaleString()}</small>
            </button>
          ))}
          {!drafts.length && <Empty text="暂无草稿。先在剧情规划中选择方案并生成章节。" />}
        </aside>
        <div className="editor-pane">
          {draft ? <>
            <div className="editor-toolbar">
              <div><span className={`status ${draft.status}`}>{statusLabels[draft.status]}</span><strong>修订版本 {draft.revision_number}</strong></div>
              <div>
                {draft.parent_draft_id && <button className="secondary" onClick={async () => {
                  try {
                    setDiff((await api.diffDrafts(draft.parent_draft_id!, draft.id)).unified_diff)
                  } catch (reason) { fail(reason) }
                }}><GitCompare size={15} />版本差异</button>}
                <button className="secondary" onClick={async () => {
                  try {
                    const blob = await api.downloadDraft(draft.id)
                    const url = URL.createObjectURL(blob)
                    const link = document.createElement('a')
                    link.href = url
                    link.download = `${draft.id}.md`
                    link.click()
                    URL.revokeObjectURL(url)
                  } catch (reason) { fail(reason) }
                }}><Download size={15} />下载</button>
              </div>
            </div>
            {diff ? <pre className="diff-view">{diff || '两个版本没有文本差异。'}</pre> : <article className="manuscript">{draft.body}</article>}
            <div className="draft-meta">
              <div><strong>创作说明</strong><p>{draft.creative_notes || '无'}</p></div>
              <div><strong>事实依据</strong><p>{draft.factual_basis_summary || '未引用外部事实'}</p></div>
            </div>
            {draft.status === 'draft' && (
              <div className="revision-box">
                <Field label="给修订 Agent 的明确意见" value={instruction} onChange={setInstruction} placeholder="例如：保留城门冲突，但让主角通过观察而不是巧合解决问题。" multiline />
                <div className="button-row">
                  <button className="danger-ghost" onClick={async () => {
                    const reason = window.prompt('拒绝原因')
                    if (!reason) return
                    try { setDraft(await api.rejectDraft(draft.id, reason)); feedback('草稿已拒绝'); await refresh(draft.id) } catch (cause) { fail(cause) }
                  }}>拒绝草稿</button>
                  <button className="secondary" disabled={!instruction || busy} onClick={() => void revise()}><RefreshCw size={16} />按意见修订</button>
                  <button className="primary" onClick={async () => {
                    try { await api.acceptDraft(draft.id); feedback('草稿已接受并更新 Canon'); await refresh(draft.id) } catch (reason) { fail(reason) }
                  }}><Check size={16} />接受为 Canon</button>
                </div>
              </div>
            )}
          </> : <Empty text="选择一个草稿开始审阅。" />}
        </div>
      </section>
    </div>
  )
}

function MemoryWorkspace({ project, fail }: { project: Project; fail: (reason: unknown) => void }) {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<MemoryHit[]>([])
  const [conflicts, setConflicts] = useState<unknown[]>([])
  const [revision, setRevision] = useState(0)
  const search = async () => {
    try {
      const result = await api.memory(project.id, query)
      setHits(result.hits); setConflicts(result.conflicts); setRevision(result.revision)
    } catch (reason) { fail(reason) }
  }
  return (
    <div className="page-stack">
      <section className="section-heading">
        <div><span className="eyebrow">Narrative memory · r{revision}</span><h2>问故事，而不是翻目录</h2><p>检索已接受章节中的人物位置、物品归属、关系与知识边界。</p></div>
      </section>
      <div className="memory-search">
        <Search size={20} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void search() }} placeholder="例如：林川现在在哪里？铜符由谁保管？" />
        <button className="primary" disabled={!query} onClick={() => void search()}>检索记忆</button>
      </div>
      {!!conflicts.length && <div className="warning-banner">发现 {conflicts.length} 条可能冲突，请在写作前确认。</div>}
      <div className="memory-grid">
        {hits.map((hit) => (
          <article key={hit.memory.id}>
            <div><span>{hit.memory.kind.replaceAll('_', ' ')}</span><small>相关度 {Math.round(hit.score * 100)}%</small></div>
            <h3>{hit.memory.subject}</h3>
            <p>{hit.memory.statement}</p>
            <footer>Canon v{hit.memory.canon_version}</footer>
          </article>
        ))}
        {!hits.length && <Empty text="输入问题，检索已接受章节中的长期记忆。" />}
      </div>
    </div>
  )
}

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return <article className="metric"><span>{label}</span><strong>{value}</strong><small>{note}</small></article>
}

function Panel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return <section className="panel"><header><h3>{title}</h3>{action}</header><div className="panel-body">{children}</div></section>
}

function EntryPanel({ title, entries }: { title: string; entries: Array<Record<string, unknown> | string> }) {
  return <Panel title={`${title} · ${entries.length}`}><ul className="entry-list">{entries.slice(0, 6).map((item, index) => <li key={index}>{typeof item === 'string' ? item : String(item.name || item.description || JSON.stringify(item))}</li>)}{!entries.length && <li className="muted">尚未设置</li>}</ul></Panel>
}

function Field({ label, value, onChange, placeholder, multiline = false, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; multiline?: boolean; type?: string }) {
  return <label className="field"><span>{label}</span>{multiline ? <textarea rows={3} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /> : <input type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />}</label>
}

function RunRow({ run }: { run: AgentRun }) {
  return <div className="run-row"><span className={`run-icon ${run.status}`}><Bot size={15} /></span><div><strong>{run.agent_name.replaceAll('_', ' ')}</strong><small>{run.model || run.provider} · {run.prompt_version}</small></div><div className="run-cost"><strong>{run.duration_ms || 0}ms</strong><small>{run.prompt_tokens + run.completion_tokens} tokens</small></div></div>
}

function Empty({ text }: { text: string }) {
  return <div className="empty"><BookOpen size={24} strokeWidth={1.4} /><span>{text}</span></div>
}

function LoadingBlock() {
  return <div className="loading-block"><RefreshCw size={18} className="spin" />读取中…</div>
}

function Toast({ kind, message, onClose }: { kind: 'error' | 'success'; message: string; onClose: () => void }) {
  return <div className={`toast ${kind}`}>{kind === 'success' ? <Check size={17} /> : <Activity size={17} />}<span>{message}</span><button onClick={onClose}><X size={15} /></button></div>
}

export default App

window.__ModuleLoader__.load({
  id: '@local/cut-workbench-dashboard',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const T = {
      bg: 'var(--dsw-alias-bg-base)',
      layer1: 'var(--dsw-alias-bg-layer-1)',
      layer2: 'var(--dsw-alias-bg-layer-2)',
      border1: 'var(--dsw-alias-border-l1)',
      border2: 'var(--dsw-alias-border-l2)',
      brand: 'var(--dsw-alias-brand-primary)',
      label1: 'var(--dsw-alias-label-primary)',
      label2: 'var(--dsw-alias-label-secondary)',
      ok: 'var(--dsw-alias-state-success-primary)',
      idle: 'var(--dsw-alias-state-idle-primary)',
      warn: 'var(--dsw-alias-state-warn-primary)',
      err: 'var(--dsw-alias-state-error-primary)',
    };

    async function loadDashboard() {
      const res = await fetch('/api/cut-workbench/dashboard-v3');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    }

    function StepChip({ step }) {
      const done = step.done === true;
      return h('span', {
        title: `${step.label}：${step.status || (done ? '已有产物' : '未确认')}`,
        style: {
          display: 'inline-flex', alignItems: 'center', gap: '5px',
          padding: '2px 9px', borderRadius: '999px',
          background: T.layer2,
          border: `1px solid ${done ? T.ok : T.border1}`,
          fontSize: '11px', lineHeight: '18px', whiteSpace: 'nowrap',
          color: done ? T.label1 : T.label2,
          fontWeight: done ? 500 : 400,
        },
      },
        h('span', {
          style: {
            width: '6px', height: '6px', borderRadius: '50%', flex: '0 0 auto',
            background: done ? T.ok : T.idle,
          },
        }),
        step.status ? step.label + '：' + step.status : step.label,
      );
    }

    function EpisodeRow({ ep, last }) {
      const doneCount = ep.steps.filter((s) => s.done).length;
      const total = ep.steps.length;
      const complete = doneCount === total;
      return h('div', {
        style: {
          padding: '12px 16px',
          borderTop: last ? 'none' : `1px solid ${T.border1}`,
        },
      },
        h('div', {
          style: {
            display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
            gap: '12px', marginBottom: '8px',
          },
        },
          h('div', {
            style: {
              fontSize: '13px', fontWeight: 500, lineHeight: '1.5',
              color: T.label1, wordBreak: 'break-word', minWidth: 0,
            },
          }, ep.subject ? ep.subject + ' · ' + ep.episode + ' · ' + ep.title : ep.title),
          h('div', {
            style: {
              flex: '0 0 auto', fontSize: '11px', whiteSpace: 'nowrap',
              color: complete ? T.ok : T.label2, fontVariantNumeric: 'tabular-nums',
            },
          }, `${doneCount}/${total}`),
        ),
        h('div', {
          style: { display: 'flex', flexWrap: 'wrap', gap: '6px' },
        }, ...ep.steps.map((s) => h(StepChip, { key: s.key, step: s }))),
        h('div', {
          style: { marginTop: '8px', fontSize: '11px', color: T.label2 },
        }, ep.note || `空镜 ${ep.shots} 段${ep.cover ? ' · 封面已出' : ' · 无封面'}`),
      );
    }

    function BatchCard({ batch }) {
      const delivered = batch.episodes.filter(e => e.reviewed).length;
      const generated = batch.episodes.filter(e => e.generated).length;
      const allDone = batch.episodes.length > 0 && delivered === batch.episodes.length;
      return h('div', {
        style: {
          background: T.layer1,
          border: `1px solid ${T.border1}`,
          borderRadius: '12px',
          overflow: 'hidden',
        },
      },
        h('div', {
          style: {
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            gap: '12px', padding: '12px 16px',
            borderBottom: `1px solid ${T.border1}`,
          },
        },
          h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 } },
            h('span', {
              style: {
                fontSize: '14px', fontWeight: 600, color: T.label1,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              },
              title: batch.name,
            }, batch.name),
          ),
          h('div', {
            style: {
              flex: '0 0 auto', fontSize: '11px', whiteSpace: 'nowrap',
              color: allDone ? T.ok : T.label2,
            },
          }, `已生成 ${generated} · 已验收 ${delivered} · 共 ${batch.videos} 期`),
        ),
        ...batch.episodes.map((ep, i) =>
          h(EpisodeRow, { key: ep.dst, ep, last: i === batch.episodes.length - 1 })),
      );
    }

    function StatChip({ label, value }) {
      return h('div', {
        style: {
          display: 'inline-flex', alignItems: 'baseline', gap: '6px',
          padding: '4px 11px', borderRadius: '8px',
          background: T.layer2, border: `1px solid ${T.border1}`,
        },
      },
        h('span', { style: { fontSize: '11px', color: T.label2 } }, label),
        h('span', {
          style: {
            fontSize: '13px', fontWeight: 600, color: T.label1,
            fontVariantNumeric: 'tabular-nums',
          },
        }, String(value)),
      );
    }

    function RefreshButton({ loading, onClick }) {
      const [hover, setHover] = React.useState(false);
      return h('button', {
        type: 'button',
        onClick,
        disabled: loading,
        onMouseEnter: () => setHover(true),
        onMouseLeave: () => setHover(false),
        style: {
          fontSize: '12px', padding: '5px 14px', borderRadius: '7px',
          cursor: loading ? 'default' : 'pointer',
          border: `1px solid ${hover && !loading ? T.brand : T.border2}`,
          background: hover && !loading ? T.layer2 : T.layer1,
          color: loading ? T.label2 : T.label1,
          transition: 'border-color 120ms, background 120ms',
        },
      }, loading ? '刷新中…' : '刷新');
    }

    function DashboardPage() {
      const [data, setData] = React.useState(null);
      const [error, setError] = React.useState(null);
      const [loading, setLoading] = React.useState(true);

      const load = React.useCallback(() => {
        let alive = true;
        setLoading(true);
        loadDashboard()
          .then((d) => { if (alive) { setData(d); setError(null); } })
          .catch((e) => { if (alive) setError(String(e && e.message ? e.message : e)) })
          .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
      }, []);

      React.useEffect(load, [load]);

      const stats = data && data.stats ? data.stats : null;

      return h('div', {
        style: {
          height: '100%', overflowY: 'auto',
          padding: '24px 28px 32px',
          background: T.bg,
          color: T.label1,
        },
      },
        h('div', { style: { maxWidth: '980px', margin: '0 auto' } },
          // header
          h('div', {
            style: {
              display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
              gap: '16px', marginBottom: '16px',
            },
          },
            h('div', null,
              h('div', {
                style: { fontSize: '17px', fontWeight: 600, color: T.label1, lineHeight: '24px' },
              }, '剪辑工作台总览'),
              h('div', {
                style: { marginTop: '4px', fontSize: '12px', color: T.label2 },
              }, data
                ? `数据目录 ${data.root} · 更新于 ${new Date(data.generatedAt).toLocaleTimeString()}`
                : '正在读取工作区…'),
            ),
            h(RefreshButton, { loading, onClick: load }),
          ),

          // stats
          stats ? h('div', {
            style: { display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' },
          },
            h(StatChip, { label: '任务 MD', value: stats.taskFiles }),
            h(StatChip, { label: '重点词任务', value: stats.hlCount }),
            h(StatChip, { label: '音效任务', value: stats.sfxCount }),
            h(StatChip, { label: '回收中间稿批次', value: stats.recycledBatches }),
          ) : null,

          // error
          error ? h('div', {
            style: {
              padding: '11px 14px', borderRadius: '9px', marginBottom: '16px',
              fontSize: '12px', lineHeight: '1.6',
              background: T.layer1, border: `1px solid ${T.err}`, color: T.label1,
            },
          },
            h('div', { style: { fontWeight: 600, color: T.err, marginBottom: '2px' } }, '数据加载失败'),
            h('div', { style: { color: T.label2 } }, error),
          ) : null,

          // loading
          loading && !data ? h('div', {
            style: { padding: '28px 0', fontSize: '12px', color: T.label2, textAlign: 'center' },
          }, '加载中…') : null,

          // batches
          data && data.batches && data.batches.length > 0 ? h('div', {
            style: { display: 'flex', flexDirection: 'column', gap: '14px' },
          }, ...data.batches.map((b) => h(BatchCard, { key: b.name, batch: b }))) : null,

          // empty
          data && (!data.batches || data.batches.length === 0) ? h('div', {
            style: {
              padding: '28px 16px', borderRadius: '12px', textAlign: 'center',
              fontSize: '12px', color: T.label2,
              background: T.layer1, border: `1px dashed ${T.border2}`,
            },
          }, '没有找到批次目录。请确认 F:\\agent\\广济医疗-医生IP-打标素材 下存在批次文件夹。') : null,
        ),
      );
    }

    function PanelIcon(props) {
      const size = props && typeof props.size === 'number' ? props.size : 20;
      return h('svg', {
        viewBox: '0 0 48 48', width: size, height: size,
        'aria-hidden': true, style: { display: 'block' },
      },
        h('rect', {
          x: 4, y: 10, width: 40, height: 28, rx: 5,
          fill: 'none', stroke: 'currentColor', 'stroke-width': 3,
        }),
        h('path', { d: 'M26 10 L22 38', stroke: 'currentColor', 'stroke-width': 3 }),
        h('path', {
          d: 'M15 20 L15 28 M11 24 L19 24',
          stroke: 'currentColor', 'stroke-width': 2.5, 'stroke-linecap': 'round',
        }),
        h('circle', { cx: 31, cy: 24, r: 3.2, fill: 'currentColor' }),
      );
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        // The sidebar owner wraps each panellist entry in its own button and
        // passes { size, active } to the icon component; we only draw.
        const disposePanelEntry = ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
          name: 'sidebar.panellist',
          id: 'cut-workbench-dashboard',
          order: 50,
          label: '剪辑工作台总览',
        }, PanelIcon));

        const disposeMainEntry = ctx.slots.inject('main', () => ctx.slots.register({
          name: 'main',
          key: 'cut-workbench-dashboard',
        }, DashboardPage));

        return () => {
          disposeMainEntry();
          disposePanelEntry();
        };
      },
    };
  },
});

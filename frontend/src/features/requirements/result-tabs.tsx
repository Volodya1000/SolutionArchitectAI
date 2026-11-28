const tabs = [
  { id: 'requirements', label: 'Требования' },
  { id: 'clarifications', label: 'Уточнения' },
  { id: 'risks', label: 'Риски' },
] as const;
export type ResultTab = (typeof tabs)[number]['id'];

export function ResultTabs({
  selected,
  counts,
  select,
}: {
  selected: ResultTab;
  counts: Record<ResultTab, number>;
  select: (tab: ResultTab) => void;
}) {
  return (
    <div role="tablist" aria-label="Результаты анализа" className="result-tabs">
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`result-tab-${tab.id}`}
          aria-controls={`result-panel-${tab.id}`}
          aria-selected={selected === tab.id}
          tabIndex={selected === tab.id ? 0 : -1}
          onClick={() => select(tab.id)}
          onKeyDown={(event) => {
            const next = nextTab(event.key, index);
            if (!next) return;
            event.preventDefault();
            select(next);
            document.getElementById(`result-tab-${next}`)?.focus();
          }}
        >
          {tab.label} <span className="tab-count">{counts[tab.id]}</span>
        </button>
      ))}
    </div>
  );
}

function nextTab(key: string, index: number): ResultTab | undefined {
  if (key === 'Home') return tabs[0].id;
  if (key === 'End') return tabs[tabs.length - 1]?.id;
  const offset = { ArrowRight: 1, ArrowLeft: -1 }[key];
  return offset ? tabs[(index + offset + tabs.length) % tabs.length]?.id : undefined;
}

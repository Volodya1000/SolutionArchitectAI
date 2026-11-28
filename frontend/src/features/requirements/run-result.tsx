import { useEffect } from 'react';
import { useLocation, useSearchParams } from 'react-router';
import { questionBlocksCompletion, type ClarificationView } from '../../shared/api/clarifications';
import { type Extraction, type Requirement } from '../../shared/api/extractions';
import { useClarifications } from '../../shared/api/use-clarifications';
import { Button } from '../../shared/ui/button';
import { QueryError } from '../../shared/ui/query-error';
import { ClarificationQuestions, ClarificationRisks } from '../clarifications';
import { ExtractionResult } from './extraction-result';
import { ResultTabs, type ResultTab } from './result-tabs';

export function RunResult({ run }: { run: Extraction }) {
  const query = useClarifications(run.id, true, run.status);
  const [search, setSearch] = useSearchParams();
  const openOnly = search.get('questions') === 'blocking';
  const tab = selectedTab(search.get('tab'));
  const view = query.data;
  const requirements: Requirement[] = view?.initialized ? view.requirements : run.requirements;
  const blockers = view?.questions.filter(questionBlocksCompletion) ?? [];
  function select(next: ResultTab, onlyBlockers = false) {
    const parameters = new URLSearchParams(search);
    parameters.set('run', run.id);
    parameters.set('tab', next);
    if (onlyBlockers) parameters.set('questions', 'blocking');
    else parameters.delete('questions');
    void setSearch(parameters);
  }
  const firstBlocker = blockers[0]?.id;
  const location = useLocation();
  useEffect(() => {
    const target = location.hash ? document.getElementById(location.hash.slice(1)) : null;
    if (target) {
      target.scrollIntoView?.({ block: 'center' });
      target.focus();
      return;
    }
    if (tab === 'clarifications' && openOnly && firstBlocker)
      document.getElementById(`question-${firstBlocker}`)?.focus();
  }, [tab, openOnly, firstBlocker, location.hash, view]);
  return (
    <div className="run-result">
      <WaitingNotice
        count={blockers.length}
        open={() => {
          select('clarifications', true);
        }}
      />
      <ResultTabs
        selected={tab}
        select={(next) => select(next)}
        counts={tabCounts(view, requirements)}
      />
      {query.isError && (
        <QueryError
          error={query.error}
          retry={() => {
            void query.refetch();
          }}
        />
      )}
      {(['requirements', 'clarifications', 'risks'] as const).map((panel) => (
        <section
          key={panel}
          role="tabpanel"
          id={`result-panel-${panel}`}
          aria-labelledby={`result-tab-${panel}`}
          hidden={tab !== panel}
        >
          {tab === panel && (
            <ResultPanel
              tab={tab}
              run={run}
              query={query}
              requirements={requirements}
              openOnly={openOnly}
              showAll={() => select('clarifications')}
            />
          )}
        </section>
      ))}
    </div>
  );
}

function selectedTab(value: string | null): ResultTab {
  return value === 'clarifications' || value === 'risks' ? value : 'requirements';
}

function tabCounts(view: ClarificationView | undefined, requirements: Requirement[]) {
  return {
    requirements: requirements.length,
    clarifications: view?.questions.length ?? 0,
    risks: view?.risks.length ?? 0,
  };
}

function WaitingNotice({ count, open }: { count: number; open: () => void }) {
  if (count === 0) return null;
  return (
    <section className="waiting-notice" aria-label="Анализ ожидает решения">
      <div>
        <strong>Для продолжения нужны решения архитектора</strong>
        <p>
          Блокирующих вопросов: {count}. Откройте вопросы и сохраните ответ или проверьте допущение.
        </p>
      </div>
      <Button type="button" onClick={open}>
        Открыть блокирующие вопросы
      </Button>
    </section>
  );
}

function ResultPanel({
  tab,
  run,
  query,
  requirements,
  openOnly,
  showAll,
}: {
  tab: ResultTab;
  run: Extraction;
  query: ReturnType<typeof useClarifications>;
  requirements: Requirement[];
  openOnly: boolean;
  showAll: () => void;
}) {
  if (tab === 'requirements')
    return (
      <ExtractionResult
        runId={run.id}
        candidates={requirements}
        questions={query.data?.questions ?? []}
        decisions={query.data?.decisions ?? []}
      />
    );
  if (query.isPending) return <p role="status">Загружаем уточнения…</p>;
  if (!query.data) return null;
  if (tab === 'risks') return <ClarificationRisks view={query.data} tabbed />;
  return (
    <>
      {openOnly && (
        <Button type="button" variant="ghost" onClick={showAll}>
          Показать все вопросы
        </Button>
      )}
      <ClarificationQuestions view={query.data} openOnly={openOnly} tabbed />
    </>
  );
}

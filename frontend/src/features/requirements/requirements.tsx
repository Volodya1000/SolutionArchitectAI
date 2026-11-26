import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { scopeKey } from '../../shared/api/client';
import {
  categories,
  categorySchema,
  extractionActive,
  extractionList,
  readExtraction,
  type Category,
  type Extraction,
} from '../../shared/api/extractions';
import { QueryError } from '../../shared/ui/query-error';
import { RequirementTable } from './requirement-table';
import { RunStatus } from './run-status';

export function Requirements() {
  const [search, setSearch] = useSearchParams();
  const runs = useQuery({ queryKey: [...scopeKey, 'extractions'], queryFn: extractionList });
  const selectedId = search.get('run') ?? runs.data?.[0]?.id;
  return (
    <div className="workspace-content">
      <div className="page-intro">
        <span className="eyebrow">A-01</span>
        <h1>A-01 · Реестр требований</h1>
        <p>
          Извлечённые кандидаты сохраняются с происхождением. Техническая проверка ссылки не
          подтверждает смысл требования и не заменяет решение человека.
        </p>
        <Link className="text-link" to="/documents">
          Выбрать документы для нового анализа
        </Link>
      </div>
      {runs.isPending && <p role="status">Загружаем историю извлечений…</p>}
      {runs.isError && (
        <QueryError
          error={runs.error}
          retry={() => {
            void runs.refetch();
          }}
        />
      )}
      {runs.data && (
        <ExtractionHistory
          runs={runs.data}
          selectedId={selectedId}
          select={(id) => setSearch({ run: id })}
        />
      )}
      {selectedId && (
        <RunPanel
          key={selectedId}
          id={selectedId}
          initial={runs.data?.find((run) => run.id === selectedId)}
        />
      )}
    </div>
  );
}

function ExtractionHistory({
  runs,
  selectedId,
  select,
}: {
  runs: Extraction[];
  selectedId: string | undefined;
  select: (id: string) => void;
}) {
  if (runs.length === 0)
    return selectedId ? null : (
      <p className="notice">Извлечений пока нет. Загрузите документы и запустите анализ.</p>
    );
  return (
    <label className="field-label">
      История извлечений
      <select
        aria-label="История извлечений"
        value={selectedId}
        onChange={(event) => select(event.target.value)}
      >
        {runs.map((run) => (
          <option key={run.id} value={run.id}>
            {new Date(run.created_at).toLocaleString('ru-RU')} · {run.model} · {run.id.slice(0, 8)}
          </option>
        ))}
      </select>
    </label>
  );
}

function RunPanel({ id, initial }: { id: string; initial: Extraction | undefined }) {
  const [category, setCategory] = useState<Category | 'all'>('all');
  const run = useQuery({
    queryKey: [...scopeKey, 'extraction', id],
    queryFn: () => readExtraction(id),
    initialData: initial,
    staleTime: Infinity,
    refetchInterval: (query) =>
      query.state.data && extractionActive(query.state.data) ? 1000 : false,
  });
  const requirements = run.data?.requirements.filter(
    (item) => category === 'all' || item.category === category,
  );
  return (
    <>
      {run.isPending && <p role="status">Загружаем результат…</p>}
      {run.isError && (
        <QueryError
          error={run.error}
          retry={() => {
            void run.refetch();
          }}
        />
      )}
      {run.data && (
        <>
          <RunStatus run={run.data} />
          <div className="section-heading">
            <label className="field-label">
              Категория требований
              <select
                value={category}
                onChange={(event) =>
                  setCategory(
                    event.target.value === 'all' ? 'all' : categorySchema.parse(event.target.value),
                  )
                }
              >
                <option value="all">Все категории</option>
                {Object.entries(categories).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <span className="notice">Кандидатов: {requirements?.length ?? 0}</span>
          </div>
          <RequirementTable requirements={requirements ?? []} />
        </>
      )}
    </>
  );
}

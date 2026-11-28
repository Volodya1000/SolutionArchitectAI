import { fixtureId } from '@/shared/api/test-network-fixtures';
import { http, HttpResponse } from 'msw';
import { extractionActive, extractionSchema, extractionSummarySchema } from './extractions';

export function mockExtractions(values: unknown[]) {
  const runs = values.map((value) => extractionSchema.parse(value));
  return [
    http.get('/api/extractions/:id/clarifications', ({ params }) =>
      HttpResponse.json({
        ...{ conflict_assessments: [] },
        metadata: null,
        resume_version: 0,

        run_id: params.id,
        history_id: fixtureId('legacy'),
        cycle: 0,
        initialized: false,
        resume_pending: false,
        questions: [],
        decisions: [],
        risks: [],
        requirements: [],
        completed_cycles: [],
      }),
    ),
    http.get('/api/extractions/history', ({ request }) => {
      const query = new URL(request.url).searchParams;
      const offset = Number(query.get('offset') ?? 0);
      const limit = Number(query.get('limit') ?? 50);
      return HttpResponse.json({
        items: runs.slice(offset, offset + limit).map((run) => extractionSummarySchema.parse(run)),
        has_more: runs.length > offset + limit,
      });
    }),
    http.get('/api/extractions/matching', ({ request }) => {
      const query = new URL(request.url).searchParams;
      const ids = query.getAll('version_ids');
      const matching = runs.filter(
        (run) =>
          run.analysis_scope === query.get('analysis_scope') &&
          run.version_ids.length === ids.length &&
          run.version_ids.every((id) => ids.includes(id)),
      );
      return HttpResponse.json({
        active: matching.find(extractionActive) ?? null,
        current_completed:
          matching.find((run) => run.status === 'completed' && run.configuration_current) ?? null,
        latest_completed: matching.find((run) => run.status === 'completed') ?? null,
      });
    }),
    http.get('/api/extractions/:id/status', ({ params }) => {
      const run = runs.find((run) => run.id === params.id);
      return run
        ? HttpResponse.json(extractionSummarySchema.parse(run))
        : new HttpResponse(null, { status: 404 });
    }),
    http.get('/api/extractions/:id', ({ params }) => {
      const run = runs.find((run) => run.id === params.id);
      return run ? HttpResponse.json(run) : new HttpResponse(null, { status: 404 });
    }),
  ];
}

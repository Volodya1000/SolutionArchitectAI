import { fixtureId } from '@/shared/api/test-network-fixtures';
import { http, HttpResponse } from 'msw';
import { extractionSchema, extractionSummarySchema } from './extractions';

export function mockExtractions(
  values: unknown[],
  matching: { active?: unknown; current_completed?: unknown; latest_completed?: unknown } = {},
) {
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
    http.get('/api/extractions/matching', () =>
      HttpResponse.json({
        active: null,
        current_completed: null,
        latest_completed: null,
        ...matching,
      }),
    ),
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

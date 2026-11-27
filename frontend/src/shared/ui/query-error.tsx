import { Button } from './button';

export function QueryError({ error, retry }: { error: Error; retry: () => void }) {
  return (
    <div className="notice error-text" role="alert">
      {error.message}{' '}
      <Button variant="ghost" onClick={retry}>
        Повторить
      </Button>
    </div>
  );
}

import { Layers3, ArrowRight } from 'lucide-react';
import { Chat } from '../features/chat';
import { Documents } from '../features/documents';
import { Requirements } from '../features/requirements';
import { Button } from '../shared/ui/button';

export type WorkspaceSection = 'chat' | 'documents' | 'requirements';

export function WorkspaceContent({
  section,
  chatId,
  pending,
  create,
}: {
  section: WorkspaceSection;
  chatId: string | undefined;
  pending: boolean;
  create: () => void;
}) {
  if (section === 'documents') return <Documents />;
  if (section === 'requirements') return <Requirements />;
  if (chatId) return <Chat key={chatId} chatId={chatId} />;
  return (
    <div className="empty-workspace">
      <div className="welcome-icon">
        <Layers3 size={30} />
      </div>
      <span className="eyebrow">SOLUTION ARCHITECT AI</span>
      <h1>Место для продуманных решений</h1>
      <p>
        Обсуждайте требования и архитектуру в отдельных диалогах. Откройте сохранённый чат или
        начните новый.
      </p>
      <Button onClick={create} disabled={pending}>
        Начать обсуждение
        <ArrowRight size={17} />
      </Button>
    </div>
  );
}

export function WorkspaceHeading({
  section,
  title,
}: {
  section: WorkspaceSection;
  title: string | undefined;
}) {
  const headings: Readonly<Record<WorkspaceSection, string>> = {
    chat: title ?? 'Рабочий чат',
    documents: 'Документы',
    requirements: 'Требования',
  };
  return (
    <div>
      <span className="breadcrumb">
        Локальный проект <span>/</span>
        {section === 'chat' ? 'Чаты' : headings[section]}
      </span>
      <h2>{headings[section]}</h2>
    </div>
  );
}

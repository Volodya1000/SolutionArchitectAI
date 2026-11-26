import { categories, type Requirement } from '../../shared/api/extractions';
import { Evidence } from './evidence';

export function RequirementTable({ requirements }: { requirements: Requirement[] }) {
  if (requirements.length === 0)
    return <p className="notice">В выбранной категории пока нет кандидатов требований.</p>;
  return (
    <div className="table-scroll">
      <table className="workspace-table requirements-table">
        <caption className="sr-only">Кандидаты требований A-01</caption>
        <thead>
          <tr>
            <th>Категория и ID</th>
            <th>Требование</th>
            <th>Происхождение</th>
          </tr>
        </thead>
        <tbody>
          {requirements.map((requirement) => (
            <tr key={requirement.id}>
              <td>
                <span className="category-label">{categories[requirement.category]}</span>
                <div className="version-meta">{requirement.id}</div>
                <p className="candidate-status">Кандидат · требует проверки человеком</p>
              </td>
              <td>
                <p className="requirement-text">{requirement.normalized_text}</p>
                <details>
                  <summary>Исходная формулировка</summary>
                  <blockquote>{requirement.original_text}</blockquote>
                </details>
              </td>
              <td>
                <Evidence sources={requirement.sources} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

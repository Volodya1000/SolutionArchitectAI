import { categories, type Requirement } from '../../shared/api/extractions';
import { Evidence } from './evidence';

export function RequirementTable({ requirements }: { requirements: Requirement[] }) {
  if (requirements.length === 0)
    return <p className="notice">В выбранной категории пока нет кандидатов требований.</p>;
  return (
    <div className="table-scroll">
      <table className="workspace-table requirements-table">
        <caption className="sr-only">Кандидаты требований</caption>
        <thead>
          <tr>
            <th>Категория</th>
            <th>Требование</th>
            <th>Происхождение</th>
          </tr>
        </thead>
        <tbody>
          {requirements.map((requirement) => (
            <tr key={requirement.id}>
              <td>
                <span className="category-label">{categories[requirement.category]}</span>
              </td>
              <td>
                <p className="requirement-text">{requirement.normalized_text}</p>
              </td>
              <td>
                <Evidence sources={requirement.sources} originalText={requirement.original_text} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

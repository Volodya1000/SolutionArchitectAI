import { z } from 'zod';
import { sendRequest } from './client';
import { ApiError } from './api-error';

const messages: Readonly<Record<string, string>> = {
  not_found: 'Источник недоступен в этой задаче. Указанная версия не заменяется новой.',
  conflict: 'Операция с этим идентификатором уже использована для других данных.',
  access_denied: 'Источник не принадлежит этой задаче.',
  file_missing: 'Оригинал этой версии отсутствует. Воспроизводимость источника нарушена.',
  file_corrupted: 'Контрольная сумма или размер оригинала не совпадает с сохранённой версией.',
  content_corrupted: 'Контрольная сумма или размер оригинала не совпадает с сохранённой версией.',
  unsupported_format: 'Формат не поддерживается. Выберите TXT или Markdown.',
  invalid_mime: 'Содержимое файла не соответствует заявленному формату.',
  too_large: 'Файл превышает допустимый размер загрузки.',
  upload_too_large: 'Файл превышает допустимый размер загрузки.',
  context_too_large:
    'Окно модели слишком мало для схемы, фрагмента и ответа. Требуется другой профиль.',
  scanned_pdf: 'В PDF отсутствует текстовый слой. OCR пока не поддерживается.',
  invalid_filename:
    'Имя файла содержит недопустимые символы. Переименуйте файл и повторите загрузку.',
  document_too_large: 'Файл превышает допустимый размер загрузки.',
  empty_document: 'В документе нет содержимого для анализа.',
  invalid_text_encoding: 'Сохраните текстовый документ в UTF-8 и загрузите его повторно.',
  document_file_missing: 'Оригинал этой версии отсутствует. Воспроизводимость источника нарушена.',
  document_file_corrupt:
    'Контрольная сумма или размер оригинала не совпадает с сохранённой версией.',
  immutable_file_conflict: 'Сохранённая версия содержит другие данные. Перезапись запрещена.',
  invalid_storage_key: 'Не удалось безопасно адресовать оригинал версии.',
  file_storage_unavailable: 'Файловое хранилище временно недоступно. Повторите запрос позже.',
  document_parse_failed: 'Не удалось прочитать структуру документа. Проверьте оригинал и формат.',
  document_has_no_text_layer: 'В PDF отсутствует текстовый слой. OCR пока не поддерживается.',
  unsupported_document_content:
    'Документ содержит элементы, которые пока нельзя воспроизводимо извлечь. Сохраните требования в TXT или Markdown.',
  parsed_document_corrupt: 'Сохранённый разбор повреждён. Источник нельзя считать воспроизводимым.',
  document_metadata_corrupt:
    'Метаданные документа повреждены. Требуется восстановление сохранённых данных.',
  stored_extraction_corrupt:
    'Сохранённое выполнение повреждено. История не заменяется новым результатом.',
  stored_result_corrupt:
    'Часть результата повреждена. Доступные кандидаты сохранены; запустите новое извлечение.',
  context_changed: 'Контекст изменился после запуска. Запустите новое извлечение выбранных версий.',
  model_profile_changed: 'Профиль модели изменился после запуска. Запустите новое извлечение.',
  json_invalid: 'Модель вернула некорректный JSON. Сохранены только успешно проверенные части.',
  schema_invalid:
    'Ответ модели не соответствует схеме. Сохранены только успешно проверенные части.',
  truncated_response: 'Ответ модели обрезан. Требуется профиль с достаточным резервом ответа.',
  budget_exhausted: 'Общий бюджет запросов исчерпан. Частичный результат сохранён.',
  deadline_exceeded: 'Время выполнения истекло. Частичный результат сохранён.',
};

export function errorText(code: string): string {
  return messages[code] ?? `Операция не завершена (${code}). Проверьте состояние и повторите.`;
}

export async function resourceRequest<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const response = await sendRequest(path, init);
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const error = z.object({ code: z.string() }).safeParse(body);
    throw new ApiError(
      response.status,
      error.success ? error.data.code : null,
      error.success
        ? errorText(error.data.code)
        : 'Не удалось выполнить запрос. Проверьте подключение и повторите.',
    );
  }
  const body: unknown = await response.json();
  return schema.parse(body);
}

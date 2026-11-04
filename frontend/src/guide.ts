import type { TabId } from './types'

export type GuideKind = 'app' | 'table'

export type GuideStep = {
  id: string
  target: string
  title: string
  body: string
  tab?: TabId
}

export const APP_TOUR: GuideStep[] = [
  {
    id: 'menu',
    target: 'guide-menu',
    title: 'Меню и справка',
    body: 'Файл обновляет окно. Стрелки влево/вправо — отменить и повторить действия этой сессии (Ctrl+Z / Ctrl+Y), как в Word. Справка — инструкция и журналы. Кнопка «?» снова открывает обучение.',
  },
  {
    id: 'tabs',
    target: 'guide-tabs',
    title: 'Три вкладки',
    body: 'Сначала объект и треугольники, затем таблица исходных данных, затем отчёт. Без выбранного объекта таблица и отчёт закрыты.',
    tab: 'object',
  },
  {
    id: 'object',
    target: 'guide-object',
    title: 'Объект',
    body: 'Выберите турбину из списка. Если объекта нет — создайте его ниже или загрузите Excel / синхронизируйте каталог.',
    tab: 'object',
  },
  {
    id: 'triangle',
    target: 'guide-triangle',
    title: 'Треугольники',
    body: 'Файл тепловиков заполняет ячейки по подписи параметра и номеру ступени. Импорт создаёт версию 0. «Добавить ступень» даёт лишнюю колонку.',
    tab: 'object',
  },
  {
    id: 'table-tab',
    target: 'guide-tab-table',
    title: 'Таблица ИД',
    body: 'Шаблон default.XLS: параметры в строках, ступени и КУ в колонках. Жёлтый — черновик, зелёный — сохранено с комментарием.',
    tab: 'table',
  },
  {
    id: 'report-tab',
    target: 'guide-tab-report',
    title: 'Отчёт',
    body: 'Короткая служебка или полная сводка в Word. Изменения относительно выбранной версии подсвечиваются. Комментарии в файл не попадают.',
    tab: 'report',
  },
  {
    id: 'notes',
    target: 'guide-notes',
    title: 'Уведомления',
    body: 'Если значение подтвердил другой автор, предыдущему приходит уведомление. Имя пользователя Windows подставляется само.',
  },
]

export const TABLE_TOUR: GuideStep[] = [
  {
    id: 'mode',
    target: 'guide-table-mode',
    title: 'Режимы таблицы',
    body: 'По умолчанию — просмотр: клик по ячейке только выделяет строку и столбец и показывает историю. Чтобы вводить значения, включите режим редактирования.',
    tab: 'table',
  },
  {
    id: 'colors',
    target: 'guide-colors',
    title: 'Цвета ячеек',
    body: 'Жёлтый — несохранённый черновик. Зелёный — зафиксировано. Серый — заголовок группы или поле, заблокированное правилом (венцовая диафрагма / ЦФБ).',
    tab: 'table',
  },
  {
    id: 'sheet',
    target: 'guide-sheet',
    title: 'Таблица',
    body: 'В режиме редактирования значение вводится в самой ячейке. Стрелки на клавиатуре переключают ячейки. Выделение подсвечивает строку и столбец. Правка без комментария остаётся жёлтой.',
    tab: 'table',
  },
  {
    id: 'edit',
    target: 'guide-edit',
    title: 'Сохранение',
    body: 'Комментарий обязателен. Можно указать ссылку на чертёж — она уйдёт в Word, комментарий нет. «Отменить черновик» возвращает последнее сохранённое значение.',
    tab: 'table',
  },
  {
    id: 'param',
    target: 'guide-add-param',
    title: 'Структура таблицы',
    body: '«Редактировать структуру»: имя, единицы, уровень вложенности, добавление и удаление строк. Меняется только текущая сводка, каталог default.XLS не трогается.',
    tab: 'table',
  },
  {
    id: 'report-type',
    target: 'guide-report-type',
    title: 'Тип сводки',
    body: 'Короткая служебка — диафрагмы, рабочие лопатки и КУ. Полная — весь каталог. Сравнение с версией подсвечивает отличия.',
    tab: 'report',
  },
  {
    id: 'report-create',
    target: 'guide-report-create',
    title: 'Выдача',
    body: '«Создать сводку» пишет Word и снимок версии. «Зафиксировать как выданную» помечает текущее состояние без файла.',
    tab: 'report',
  },
]

export function tourSteps(kind: GuideKind): GuideStep[] {
  return kind === 'app' ? APP_TOUR : TABLE_TOUR
}

export const GUIDE_SEEN_KEY = 'grand_summary_guide_offered'

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import ApplicationPage from './ApplicationPage';
const json = (data: unknown, headers: Record<string, string> = {}) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json', ...headers } });
const offer = { kind: 'COUNTER', amount_rub: 780_000, term_months: 24, rate_percent: 20, monthly_payment_rub: 39_699, valid_until: '2026-10-26T00:00:00Z', explanation: 'Меньшая сумма' };
const info = { id: 'i', round: 1, items: [{ code: 'DOCUMENT_MISSING', message: 'Приложите счёт поставщика', doc_type: 'SUPPLIER_INVOICE' }] };

function show(status: string, next_action: string, extra: Record<string, unknown> = {}) {
  const app = { id: 'a1', status, next_action, status_title: 'Заголовок', status_description: 'Пояснение', product_code: 'WORKING_CAPITAL', amount_rub: 1_000_000, term_months: 12, updated_at: '2026-10-22T00:00:00Z', version: 3, ...extra };
  vi.stubGlobal('fetch', async (url: string) => url.endsWith('/history') ? json([]) : url.endsWith('/offer') ? json(offer) : url.endsWith('/info-request') ? json(info)
    : url.endsWith('/events') ? new Response(null, { status: 404 }) : json(app, { ETag: '"3"' }));
  render(<MemoryRouter initialEntries={['/app/a1']}><Routes><Route path="/app/:id" element={<ApplicationPage />} /></Routes></MemoryRouter>);
}

describe('страница заявки по next_action', () => {
  it('FILL_DRAFT — предлагает заполнить или отменить черновик', async () => {
    show('DRAFT', 'FILL_DRAFT');
    expect(await screen.findByText('Заявка ещё не отправлена')).toBeInTheDocument();
    expect(screen.getByText('Отменить черновик')).toBeInTheDocument();
  });
  it('ANSWER_INFO_REQUEST — показывает, что запросил банк', async () => {
    show('NEEDS_INFO', 'ANSWER_INFO_REQUEST');
    expect(await screen.findByText('Приложите счёт поставщика')).toBeInTheDocument();
    expect(screen.getByText('Отправить ответ')).toBeInTheDocument();
  });
  it('REVIEW_OFFER — условия и кнопки принять/отказаться', async () => {
    show('COUNTER_OFFER', 'REVIEW_OFFER');
    expect(await screen.findByText('Банк предлагает другие условия')).toBeInTheDocument();
    expect(screen.getByText('Принять')).toBeInTheDocument();
    expect(screen.getByText('Отказаться')).toBeInTheDocument();
  });
  it('SIGN — кнопка подписать', async () => {
    show('SIGNING', 'SIGN');
    expect(await screen.findByText('Подписать')).toBeInTheDocument();
  });
  it('NONE — только статус, без действий', async () => {
    show('SCORING', 'NONE');
    expect(await screen.findByText('Заголовок')).toBeInTheDocument();
    for (const t of ['Подписать', 'Принять', 'Отправить ответ', 'Отменить черновик']) expect(screen.queryByText(t)).not.toBeInTheDocument();
  });
  it('REJECTED — причины для клиента', async () => {
    show('REJECTED', 'NONE', { reason_messages: ['Совокупная оценка заявки ниже требуемой'] });
    expect(await screen.findByText('Совокупная оценка заявки ниже требуемой')).toBeInTheDocument();
  });
});

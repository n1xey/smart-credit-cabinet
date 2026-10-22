import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Wizard from './Wizard';
const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
const products = [{ code: 'WORKING_CAPITAL', name: 'Оборотный кредит', min_amount_rub: 300_000, max_amount_rub: 10_000_000, min_term_months: 3, max_term_months: 24, base_rate_percent: 18, required_documents: [] }];

describe('мастер заявки', () => {
  // регрессия: мастер падал, если /products/recommend вернул продукт, которого нет в /products
  it('не падает на рекомендации неизвестного продукта', async () => {
    vi.stubGlobal('fetch', async (url: string) => url.endsWith('/recommend') ? json({ product_code: 'UNKNOWN', explanation: 'x' }) : json(products));
    render(<MemoryRouter><Wizard /></MemoryRouter>);
    expect(await screen.findByText('Оборотный кредит')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Нужны деньги срочно'));
    expect(await screen.findByText(/Рекомендуем: UNKNOWN/)).toBeInTheDocument();
    expect(screen.getByText('Для чего нужны деньги?')).toBeInTheDocument();
  });
  it('рекомендованный продукт выбирается', async () => {
    vi.stubGlobal('fetch', async (url: string) => url.endsWith('/recommend') ? json({ product_code: 'WORKING_CAPITAL', explanation: 'Подходит для закупок' }) : json(products));
    render(<MemoryRouter><Wizard /></MemoryRouter>);
    fireEvent.click(await screen.findByText('Закупки, зарплаты, текущие расходы'));
    expect(await screen.findByText('Подходит для закупок')).toBeInTheDocument();
    expect(screen.getByRole('button', { pressed: true })).toHaveTextContent('Оборотный кредит');
  });
});

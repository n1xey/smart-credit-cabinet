import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Company, { registryDiff } from './Company';
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const bank = { inn: '0000001011', name: 'ООО «Ромашка Логистик»', legal_form: 'OOO' as const, okved: '62', address: 'г. Москва, ул. Примерная, д. 1' };

describe('сверка профиля с реестром', () => {
  it('без расхождений — пусто, регистр и пробелы не считаются', () => expect(registryDiff(bank, { ...bank, name: ' ооо «ромашка логистик» ' })).toEqual([]));
  it('находит отличающиеся поля', () =>
    expect(registryDiff(bank, { ...bank, address: 'г. Казань', legal_form: 'IP' }).map(d => [d.label, d.ours, d.registry]))
      .toEqual([['Форма', 'ООО', 'ИП'], ['Адрес', 'г. Москва, ул. Примерная, д. 1', 'г. Казань']]));
  it('профиль из банка: ИНН не редактируется, кнопка «Сверить с реестром» показывает расхождения', async () => {
    vi.stubGlobal('fetch', async (url: string) => url.includes('/lookup') ? json({ ...bank, address: 'г. Казань' }) : json(bank));
    render(<MemoryRouter><Company /></MemoryRouter>);
    expect(await screen.findByDisplayValue('0000001011')).toBeDisabled();
    fireEvent.click(screen.getByText('Сверить с реестром'));
    expect(await screen.findByText('Сведения отличаются от реестра')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Взять данные из реестра'));
    expect(screen.getByDisplayValue('г. Казань')).toBeInTheDocument();
  });
});

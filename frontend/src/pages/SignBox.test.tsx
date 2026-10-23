import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { SignBox } from './ApplicationPage';
// CodeInput — по одному полю на цифру; вводим код посимвольно
const type = (code: string) => screen.getAllByRole('textbox').slice(0, code.length).forEach((el, i) => fireEvent.change(el, { target: { value: code[i] } }));

describe('подписание кодом (имитация)', () => {
  it('неверный код не подписывает и объясняет ошибку', async () => {
    const onSign = vi.fn(); render(<SignBox code="123456" onSign={onSign} />);
    type('654321');
    expect(await screen.findByText(/Неверный код/)).toBeInTheDocument();
    expect(onSign).not.toHaveBeenCalled();
  });
  it('верный код из подсказки подписывает', async () => {
    const onSign = vi.fn(); render(<SignBox code="123456" onSign={onSign} />);
    expect(screen.getByText('Код подтверждения: 123456')).toBeInTheDocument();
    type('123456');
    await vi.waitFor(() => expect(onSign).toHaveBeenCalledOnce());
  });
});

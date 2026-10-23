import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../auth';
import Login from './Login';

describe('вход', () => {
  it('только вход под учётной записью банка, без регистрации', () => {
    render(<MemoryRouter><AuthProvider><Login /></AuthProvider></MemoryRouter>);
    expect(screen.getByText('Вход в кабинет')).toBeInTheDocument();
    expect(screen.queryByText(/регистр/i)).not.toBeInTheDocument();
  });
});

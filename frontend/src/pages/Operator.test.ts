import { describe, expect, it } from 'vitest';
import { decisionBody, DecisionForm, validateDecision } from './Operator';
const form = (p: Partial<DecisionForm>): DecisionForm => ({ outcome: 'OFFER', comment: 'Подходит', amount: '500000', term: '12', rate: '18', info: '', reasons: [], ...p });

describe('решение оператора', () => {
  it('отказ без причин не отправляется', () => expect(validateDecision(form({ outcome: 'REJECTED' }))).toMatch(/причину отказа/));
  it('отказ с причиной уходит с reason_codes', () => {
    const d = form({ outcome: 'REJECTED', reasons: ['LOW_SCORE'] });
    expect(validateDecision(d)).toBeNull();
    expect(decisionBody(d)).toEqual({ outcome: 'REJECTED', comment: 'Подходит', reason_codes: ['LOW_SCORE'] });
  });
  it('дробная сумма или срок не проходят', () => {
    expect(validateDecision(form({ amount: '500000.5' }))).toMatch(/Сумма/);
    expect(validateDecision(form({ term: '1.5' }))).toMatch(/Срок/);
  });
  it('оффер отправляется целыми рублями и месяцами', () =>
    expect(decisionBody(form({ amount: '780000', term: '24', rate: '20.0' })).offer).toEqual({ amount_rub: 780_000, term_months: 24, rate_percent: 20 }));
  it('комментарий обязателен', () => expect(validateDecision(form({ comment: ' a ' }))).toMatch(/комментарий/));
});

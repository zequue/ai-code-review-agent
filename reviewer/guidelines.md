# Team review guidelines

Rules this team expects every change to follow. Treat a violation as a real finding.
Edit this file to adapt the reviewer to another codebase; it is sent to the model as-is.

## Money (category: money)
- Prices, discounts and totals are integer cents. Converting money to float (dividing by 100,
  multiplying by a percentage with `/`) or truncating with `int()` is a bug: severity high.
- Discounts must never make a total negative.

## Security (category: security)
- SQL must use parameterized queries (`?` placeholders). Building SQL with f-strings, `%` or `+`
  is SQL injection: severity critical.
- Secrets never live in code.

## Authentication and authorization (category: auth)
- Every administrative endpoint (paths under `/admin`, or anything that creates, edits or deletes
  catalog data) must verify the caller's credentials before doing any work. An admin endpoint
  without an authentication check is severity critical.

## Business rules (category: business-logic)
- Coupons are single-use. Applying a coupon must check that it has not been used and mark it as
  used in the same transaction as the order. A coupon that can be reused is severity high.
- Stock must be validated before an order is created.

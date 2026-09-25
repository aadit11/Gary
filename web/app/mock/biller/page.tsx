import bills from "@/lib/mock-data/bills.json";

export default function MockBiller() {
  return (
    <>
      <h1>Mock biller</h1>
      <p className="muted">GET /api/mock/biller/bills, POST /api/mock/biller/pay</p>
      <table>
        <thead><tr><th>Payee</th><th>Account</th><th>Amount</th><th>Due</th></tr></thead>
        <tbody>
          {bills.map((b) => (
            <tr key={b.id}><td>{b.payee}</td><td>{b.account}</td><td>${b.amount.toFixed(2)}</td><td>{b.due_date}</td></tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

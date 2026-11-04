def register_applicant(client, record_book='TEST-001', first_name='Иван', last_name='Иванов'):
    client.get('/account/register')
    with client.session_transaction() as session:
        csrf = session['csrf_token']
    response = client.post('/account/register', data={
        'csrf_token': csrf, 'first_name': first_name, 'last_name': last_name,
        'record_book': record_book, 'password': 'student-password', 'password_confirm': 'student-password',
    })
    if response.status_code != 302:
        raise AssertionError(response.get_data(as_text=True))
    with client.session_transaction() as session:
        return session['applicant_id']

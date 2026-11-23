"""Notebook adapter: preserve upstream auth, provision one owner, close public signup."""
import os
import sqlalchemy as sa
from fastapi.responses import JSONResponse
from studio import auth, config, db
from studio.server import app


def provision():
    db.init()
    email = os.environ['PEAKCUT_OWNER_EMAIL'].strip().lower()
    password = os.environ['PEAKCUT_OWNER_PASSWORD']
    if len(password) < 12:
        raise ValueError('Owner password must have at least 12 characters')
    with db.engine.connect() as conn:
        user = conn.execute(sa.select(db.users).where(db.users.c.email == email)).first()
    if user is None:
        user, _ = auth.signup(email, password, 'Creator')
    else:
        auth.login(email, password)  # never silently overwrite a restored password
    with db.engine.begin() as conn:
        conn.execute(db.users.update().where(db.users.c.id == user.id).values(is_admin=True))
    auth.mark_verified(user.id)
    return user.id


@app.middleware('http')
async def private_install(request, call_next):
    # Social OAuth remains enabled; Google website sign-in could create extra users.
    if request.url.path in ('/signup', '/api/auth/signup') or request.url.path.startswith('/auth/google/'):
        return JSONResponse({'detail': 'Private installation. Sign in with the notebook owner account.'}, status_code=403)
    return await call_next(request)


if __name__ == '__main__':
    import uvicorn
    provision()
    uvicorn.run(app, host='127.0.0.1', port=config.PORT, proxy_headers=False, log_level='warning')

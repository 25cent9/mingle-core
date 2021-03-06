"""Utility functions for using authentication"""
from functools import wraps
from flask_cors import cross_origin
import json
from werkzeug.exceptions import HTTPException

from flask import Blueprint, jsonify, redirect, session, url_for, _request_ctx_stack, request
from jose import jwt
from app.serve import CLIENT_ID, SECRET_KEY, app, API_AUDIENCE, AUTH0_DOMAIN
from authlib.flask.client import OAuth
from six.moves.urllib.request import urlopen
from six.moves.urllib.parse import urlencode

from app.users.utils import add_user

ALGORITHMS = ["RS256"]
auth = Blueprint('auth', __name__, url_prefix='/api/v1/auth')

oauth = OAuth(app)

auth0 = oauth.register(
    'auth0',
    client_id=CLIENT_ID,
    client_secret=SECRET_KEY,
    api_base_url='https://durian-inc.auth0.com',
    access_token_url='https://durian-inc.auth0.com/oauth/token',
    authorize_url='https://durian-inc.auth0.com/authorize',
    client_kwargs={
        'scope': 'openid profile',
    },
)

# TODO: Make above urls environment variables


def requires_auth(func):
    """Decorator to specify that function needs to be authenticated"""

    @wraps(func)
    def decorated(*args, **kwargs):
        """Check authentication, or get failure"""
        if 'profile' not in session:
            # Redirect to Login page here
            return jsonify(success=False, error="Authentication failure")
        return func(*args, **kwargs)

    return decorated


# Error handler
class AuthError(Exception):
    def __init__(self, error, status_code):
        self.error = error
        self.status_code = status_code


@app.errorhandler(AuthError)
def handle_auth_error(ex):
    response = jsonify(ex.error)
    response.status_code = ex.status_code
    return response


def get_token_auth_header():
    """Obtains the Access Token from the Authorization Header
    """
    auth = request.headers.get("Authorization", None)
    if not auth:
        raise AuthError({
            "code": "authorization_header_missing",
            "description": "Authorization header is expected"
        }, 401)

    parts = auth.split()

    if parts[0].lower() != "bearer":
        raise AuthError(
            {
                "code": "invalid_header",
                "description": "Authorization header must start with"
                " Bearer"
            }, 401)
    elif len(parts) == 1:
        raise AuthError({
            "code": "invalid_header",
            "description": "Token not found"
        }, 401)
    elif len(parts) > 2:
        raise AuthError(
            {
                "code": "invalid_header",
                "description": "Authorization header must be"
                " Bearer token"
            }, 401)

    token = parts[1]
    return token


def requires_auth_token(f):
    """Determines if the Access Token is valid"""

    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_auth_header()
        jsonurl = urlopen("https://" + AUTH0_DOMAIN + "/.well-known/jwks.json")
        jwks = json.loads(jsonurl.read())
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
        if rsa_key:
            try:
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=ALGORITHMS,
                    audience=API_AUDIENCE,
                    issuer=AUTH0_DOMAIN + "/")
            except jwt.ExpiredSignatureError:
                raise AuthError({
                    "code": "token_expired",
                    "description": "token is expired"
                }, 401)
            except jwt.JWTClaimsError:
                raise AuthError({
                    "code":
                    "invalid_claims",
                    "description":
                    "incorrect claims,"
                    "please check the audience and issuer"
                }, 401)
            except Exception:
                raise AuthError(
                    {
                        "code": "invalid_header",
                        "description": "Unable to parse authentication"
                        " token."
                    }, 401)
            _request_ctx_stack.top.current_user = payload
            return f(*args, **kwargs)
        raise AuthError({
            "code": "invalid_header",
            "description": "Unable to find appropriate key"
        }, 401)

    return decorated


def requires_scope(required_scope):
    """Determines if the required scope is present in the Access Token
    Args:
        required_scope (str): The scope required to access the resource
    """
    token = get_token_auth_header()
    unverified_claims = jwt.get_unverified_claims(token)
    if unverified_claims.get("scope"):
        token_scopes = unverified_claims["scope"].split()
        for token_scope in token_scopes:
            print(token_scope)
            if token_scope == required_scope:
                return True
    return False


@auth.route('/callback', methods=['GET'])
def callback_handling():
    """Handles response from token endpoint to get the userinfo"""
    auth0.authorize_access_token()
    resp = auth0.get('userinfo')
    userinfo = resp.json()

    # Store the user information in flask session.
    session['jwt_payload'] = userinfo
    session['profile'] = {
        'user_id': userinfo['sub'],
        'name': userinfo['name'],
        'picture': userinfo['picture']
    }

    res = add_user(userinfo['name'], userinfo['picture'], userinfo['sub'])
    if res:
        return jsonify(success=False, error=res)
    return redirect(url_for('users.list_all_users'))


@auth.route('/login', methods=['GET'])
def login():
    """Access the login page"""
    return auth0.authorize_redirect(
        redirect_uri='http://localhost:8080/api/v1/auth/callback',
        audience='https://durian-inc.auth0.com/userinfo')


@auth.route('/logout', methods=['GET'])
def logout():
    """Removes user login details from session, logging out the user"""
    session.clear()
    # TODO: Make clear only significant session storage
    # TODO: Handle error messages and auth for this function
    # Redirect user to logout endpoint
    params = {
        'returnTo': url_for('auth.api_public', _external=True),
        'client_id': CLIENT_ID
    }
    return redirect(auth0.api_base_url + '/v2/logout?' + urlencode(params))


@auth.route('/public', methods=['GET', 'POST'])
@cross_origin(headers=['Content-Type', 'Authorization'])
def api_public():
    # return(request.headers['Authorization'])
    # return(jsonify(dict(request.headers)))
    """
        Route that requires no authentication.
    """
    response = "No login necessary"
    return jsonify(message=response)


@auth.route('/private', methods=['GET', 'POST'])
@cross_origin(headers=['Content-Type', 'Authorization'])
@requires_auth_token
def api_private():
    """
        Route that requires authentication
    """
    response = "You are likely logged in so you good."
    return jsonify(message=response)

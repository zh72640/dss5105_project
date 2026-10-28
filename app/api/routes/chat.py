from typing import Literal
from fastapi import APIRouter, Depends, Response, Query
from app.api.dependencies import require_user, get_model_registry, Context
from app.api.errors import ApiError
from app.schemas.chat import ChatCreateInput, ChatTurnInput, ChatOutput, ChatEndRequestInput
from app.services.chat import service as chat
from app.services.chat.request_runs import end_request

router=APIRouter(prefix='/chat',tags=['Chat v2'])


def call(function, *args, **kwargs):
    try:
        return function(*args,**kwargs)
    except chat.ChatError as error:
        raise ApiError(error.status,error.code,str(error),details=error.details) from None


@router.post('/sessions',response_model=ChatOutput)
def create(body:ChatCreateInput,response:Response,ctx:Context=Depends(require_user),registry=Depends(get_model_registry)):
    payload=call(chat.create,**body.model_dump(),owner=ctx.username,db_path=ctx.settings.db_path,as_of=ctx.settings.as_of,registry=registry)
    response.status_code=payload.get('http_status',200)
    return payload


@router.get('/sessions')
def sessions(after:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),ctx:Context=Depends(require_user)):
    return call(chat.list_sessions,owner=ctx.username,db_path=ctx.settings.db_path,after=after,limit=limit)


@router.get('/recommendations')
def recommendations(after:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),
    status:Literal['valid','superseded','confirmed']|None=None,ctx:Context=Depends(require_user)):
    return call(chat.list_recommendations,owner=ctx.username,db_path=ctx.settings.db_path,after=after,limit=limit,status=status)


@router.get('/sessions/{session_id}')
def inspect(session_id:str,ctx:Context=Depends(require_user)):
    return call(chat.inspect,session_id,owner=ctx.username,db_path=ctx.settings.db_path)


@router.get('/sessions/{session_id}/messages')
def messages(session_id:str,after:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),ctx:Context=Depends(require_user)):
    return call(chat.list_messages,session_id,owner=ctx.username,db_path=ctx.settings.db_path,after=after,limit=limit)


@router.get('/sessions/{session_id}/trace')
def trace(session_id:str,limit:int=Query(100,ge=1,le=200),ctx:Context=Depends(require_user)):
    return call(chat.execution_trace,session_id,owner=ctx.username,db_path=ctx.settings.db_path,limit=limit)


@router.post('/sessions/{session_id}/turns',response_model=ChatOutput)
def turn(session_id:str,body:ChatTurnInput,response:Response,ctx:Context=Depends(require_user),registry=Depends(get_model_registry)):
    payload=call(chat.turn,session_id,**body.model_dump(),owner=ctx.username,db_path=ctx.settings.db_path,registry=registry)
    response.status_code=payload.get('http_status',200)
    return payload


@router.post('/sessions/{session_id}/requests/{request_id}/end')
def end(session_id:str,request_id:str,body:ChatEndRequestInput,ctx:Context=Depends(require_user)):
    return call(end_request,session_id,request_id=request_id,expected_version=body.expected_version,
                owner=ctx.username,db_path=ctx.settings.db_path)

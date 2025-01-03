from fastapi import FastAPI,UploadFile,File,Depends,Form
from fastapi.responses import RedirectResponse
# from langserve import add_routes
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field,ValidationError
from fastapi import Depends, FastAPI, Header, HTTPException
from api_model import GraphBuilder
from log import logger
from init_config import load_settings
from langchain_ollama import ChatOllama
import base64
import requests
from output_format import FlyTask

settings = load_settings()
# 1.llm 该模型可以调用 with_structed 接口进行输出
# 实现 text-to-txt 任务格式输出


# text_llm = ChatOpenAI(
#     temperature=0.0,
#     # model="gpt-3.5-turbo-16k",
#     model=settings.openai_model,
#     api_key=settings.openai_api_key,
#     base_url=settings.openai_api_base
# )
text_llm = ChatOllama(model=settings.ollama_model,
                 temperature=0.3,
                 keep_alive=10 * 60,
                 top_k=10)

image_llm = ChatOllama(model=settings.ollama_multimodal,
                 temperature=0.3,
                 keep_alive=10 * 60)
logger.info("加载ollama大模型({settings.ollama_multimodal})成功")

graph_builder = GraphBuilder()
graph_builder.set_settings(settings)
graph_builder.set_llm(text_llm)
graph_builder.set_image_llm(image_llm)
graph = graph_builder.build()

app = FastAPI(
    title="LangChain Server",
    version="1.0",
    description="A simple api server using Langchain's Runnable interfaces",)

@app.get("/")
def read_root():
    return {"Hello": "World"}

class TaskDescription(BaseModel):
    thread_id: str = Field(description="标识一个session")
    text: str = Field(description = "标识用户的文字输入")



@app.post("/masifan/v1")
async def get_task_v1(task:TaskDescription):
    config = {"configurable":{"thread_id":task.thread_id,"run_name":"text call"}}
    # 这里的调用方式 更改了，减少了 token 的使用量
    res = (await graph.ainvoke({"messages":[('user',task.text)]},config=config))["task"]
    if res.task is None:
        res.task = FlyTask()
    return res

# 这个地方不加上 =Depends() 就会报错,加上后会使得 request-type'Content-Type: multipart/form-data'
@app.post("/masifan/v2")
async def get_task_v2(task:TaskDescription=Depends(),image_file:UploadFile=File(...)):
    config = {"configurable":{"thread_id":task.thread_id,"run_name":"text and image call"}}
    text_from_image = ""
    if image_file is not None:
        import hashlib,os
        # 保存 image_file 到 ../session/thread_id/
        # 并且使用 MD5 算法重命名图片
        # 生成 MD5 哈希值
        image_data = await image_file.read()
        image_hash = hashlib.md5(image_data).hexdigest()
        
        
        # 生成图片名称
        if image_file.content_type == "image/png":
            image_name = f"{image_hash}.png"
        else:
            image_name = f"{image_hash}.jpeg"
        
        # 生成图片路径
        image_dir = os.path.join("../session/", task.thread_id)
        os.makedirs(image_dir, exist_ok=True)  # 确保目录存在
        image_path = os.path.join(image_dir, image_name)
        
        # 保存图片
        with open(image_path, "wb") as f:
            f.write(image_data)
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        text_from_image = await graph_builder.image_llm.ainvoke(\
            [(\
                'user',[\
                    {"type":"text","text":"请描述一下这张图片中主要物体的特征"},\
                    {"type":"image_url","image_url":f"data:image/jpeg;base64,{image_base64}"}]\
                )]\
                )

    return (await graph.ainvoke({"messages":[('user',task.text+text_from_image.content)]}, config=config))["task"]
    # return await graph.ainvoke({"messages":[('user',[{"type":"text","text":task.text},{"type":"image_url","image_url":f"data:image/jpeg;base64,{image_base64}"}])]}, config=config)

def make_audio_request(audio_path):
    url = "http://localhost:8001/"
    headers = {'Content-Type': 'application/json'}
    with open(audio_path, "rb") as f:
        wav = base64.b64encode(f.read()).decode()
    data = {"wav": wav}
    response = requests.post(url+"asr", headers=headers, json=data)
    response = response.json()
    if response['code'] == 0:
        res = response['res']
        return res
    else:
        return response['msg']
# 这个地方不加上 =Depends() 就会报错,加上后会使得 request-type'Content-Type: multipart/form-data'
@app.post("/masifan/v3")
async def get_task_v2(task:TaskDescription=Depends(),audio_file:UploadFile=File(...)):
    config = {"configurable":{"thread_id":task.thread_id,"run_name":"audio call"}}
    if audio_file is not None:
        if audio_file.content_type != "audio/wav":
            raise HTTPException(status_code=404, detail="audio file type is not wav")

        import hashlib,os
        image_hash = hashlib.md5(await audio_file.read()).hexdigest()
        
        await audio_file.seek(0)
        
        audio_name = f"{image_hash}.wav"
        
        audio_dir = os.path.join("../session/", task.thread_id)
        os.makedirs(audio_dir, exist_ok=True)  # 确保目录存在
        audio_path = os.path.join(audio_dir, audio_name)
        
        with open(audio_path, "wb") as f:
            f.write(await audio_file.read())

        ss = make_audio_request(audio_path)

    return (await graph.ainvoke({"messages":[('user',ss)]}, config=config))["task"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)



if __name__ == "__main__":
    import uvicorn

    logger.info("服务器启动 0.0.0.0 8000")
    uvicorn.run(app='server:app', host="0.0.0.0", port=8000)


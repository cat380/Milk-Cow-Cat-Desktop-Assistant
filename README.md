# 奶牛猫桌面助手

现在这版做了更简洁、更前卫的彩虹霓虹风格，并且只依赖项目根目录里的视频素材，不再依赖 `assets` 文件夹或原始图片。

## 当前功能

- 左上角 16:9 视频主视觉
- 开始专注时自动播放视频
- 暂停、重置或专注结束时暂停视频
- 更简洁的深色桌面 UI
- “今日路线”滚动区域，支持鼠标滚轮上下滑动
- 今日任务清单，可勾选并自动保存
- 专注计时器，可开始、暂停、重置
- 便签区，关闭窗口后保留内容

## 运行方式

```powershell
python app.py
```

也可以直接双击 [launch_assistant.bat](/C:/Users/Guo/Desktop/ctry/launch_assistant.bat) 启动。

## 跨电脑使用说明

- 直接拷贝项目文件夹到另一台电脑时，目标电脑仍然需要可用的 `Python 3`
- 还需要安装 [requirements.txt](/C:/Users/Guo/Desktop/ctry/requirements.txt) 中的依赖
- 新版 [launch_assistant.bat](/C:/Users/Guo/Desktop/ctry/launch_assistant.bat) 会自动检查这些条件
- 如果启动失败，命令行窗口不会立刻消失，并会把原因写入 [launcher_runtime.log](/C:/Users/Guo/Desktop/ctry/launcher_runtime.log)

## 素材说明

- 程序会优先读取项目根目录下名为 `video.*` 的视频文件
- 当前项目视频为 [video.mp4](/C:/Users/Guo/Desktop/ctry/video.mp4)
- 不再依赖 `assets` 文件夹或图片素材
- 如果视频缺失，界面会显示代码生成的占位画面，而不是去找旧图片

## 主要文件

- [app.py](/C:/Users/Guo/Desktop/ctry/app.py)
- [video.mp4](/C:/Users/Guo/Desktop/ctry/video.mp4)
- [assistant_state.json](/C:/Users/Guo/Desktop/ctry/assistant_state.json)

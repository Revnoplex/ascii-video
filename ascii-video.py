#!/usr/bin/env python3
import signal
import subprocess
import traceback
from io import BytesIO
import time
from multiprocessing import Manager, Process, Queue, Value
import sys
import ctypes
import datetime
from types import TracebackType
from typing import Union
from PIL import Image
import cv2
import os

if sys.version_info[1] < 10:
    def exception_handler(exception_type: BaseException, exception: BaseException,
                          exception_traceback: Union[TracebackType, list]):
        if exception_type in [KeyboardInterrupt, EOFError, SystemExit]:
            return
        else:
            print("Traceback (most recent call last):")
            if isinstance(exception_traceback, TracebackType):
                traceback.print_tb(exception_traceback)
            else:
                traceback.print_list(exception_traceback)
            print(f'{exception_type.__name__}: {exception}', file=sys.stderr)
            exit(1)
else:
    def exception_handler(exception_type: type[BaseException], exception: BaseException,
                          exception_traceback: Union[TracebackType, list[traceback.FrameSummary]]):
        if exception_type in [KeyboardInterrupt, EOFError, SystemExit]:
            return
        else:
            print("Traceback (most recent call last):")
            if isinstance(exception_traceback, TracebackType):
                traceback.print_tb(exception_traceback)
            else:
                traceback.print_list(exception_traceback)
            print(f'{exception_type.__name__}: {exception}', file=sys.stderr)
            exit(1)


sys.excepthook = exception_handler

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
if os.getenv('PYGAME_HIDE_SUPPORT_PROMPT') == "hide":
    import pygame


def dump_frames(frames: Queue, dumped_frames: Value, dumping_interval: Value,
                error: Queue, video_filename: str, total_frame_count: int):
    try:
        print("beginning to dump frames...")
        current_frame = 0
        vid = cv2.VideoCapture(video_filename)
        avg_interval_list = []
        terminal_lines, terminal_columns = (lambda px: (px.lines, px.columns))(os.get_terminal_size())
        while True:
            start_time = datetime.datetime.now()
            if not vid.isOpened():
                raise Exception("open-cv failed to open video")
            average_interval = 1.0
            if len(avg_interval_list) > 0:
                average_interval = sum(avg_interval_list)/len(avg_interval_list)
            dumping_interval.value = average_interval
            dumped_frames.value = current_frame
            status, vid_frame = vid.read()
            raw_frame = cv2.imencode(".jpg", vid_frame)[1].tobytes()
            frame = Image.open(BytesIO(raw_frame))
            resized_frame = frame.resize((terminal_columns, terminal_lines))

            img_data = resized_frame.getdata()
            ascii_gradients = [' ', '.', "'", '`', '^', '"', ',', ':', ';', 'I', 'l', '!', 'i', '>', '<', '~', '+',
                               '_', '-', '?', ']', '[', '}', '{', '1', ')', '(', '|', '\\', '/', 't', 'f', 'j', 'r',
                               'x', 'n', 'u', 'v', 'c', 'z', 'X', 'Y', 'U', 'J', 'C', 'L', 'Q', '0', 'O', 'Z', 'm',
                               'w', 'q', 'p', 'd', 'b', 'k', 'h', 'a', 'o', '*', '#', 'M', 'W', '&', '8', '%', 'B',
                               '@', '$']
            frame_width = resized_frame.width
            h_line_idx = 0
            frame_list: list[list[int, list[list[str, int]]]] = []
            line = ""
            for index, pixel in enumerate(img_data):
                if index % frame_width:
                    average_pixel_gradient = sum(pixel) / 3
                    line += ascii_gradients[int(int(average_pixel_gradient) // (255 / (len(ascii_gradients) - 1)))]
                else:
                    if h_line_idx < terminal_lines - 1:
                        frame_list.append([h_line_idx, line])
                    h_line_idx += 1
                    line = ""

            frames.put(frame_list)
            current_frame += 1
            duration = (datetime.datetime.now() - start_time).total_seconds()
            avg_interval_list.append(duration)
            if current_frame == total_frame_count:
                break
        exit()
    except Exception as e:
        error.put((type(e), e, traceback.extract_tb(e.__traceback__)))


lag = 0


def print_frames(frames: Queue, dumped_frames: Value, dumping_interval: Value,
                 child_error: Queue):
    pygame.init()
    print("Extracting audio from video file...")
    try:
        audio = subprocess.Popen(["ffmpeg", "-i", video_file, "-loglevel", "panic", "-f", "mp3",
                                  "pipe:1"],
                                 stdout=subprocess.PIPE)
    except FileNotFoundError:
        print(f"\033[1;31mError\033[0m: ffmpeg executable not found. please make sure you install ffmpeg or make sure "
              f"the executable is in one of your PATH directories.")
        exit()
    else:
        pygame.mixer.music.load(BytesIO(audio.stdout.read()))

    while True:
        average_fps = 1 // dumping_interval.value
        time_left = dumping_interval.value * (total_frames-dumped_frames.value)
        if not time_left > video_duration:
            break
        if child_error.qsize() > 0:
            return child_error.get()
        print(f"\rDumping frame {dumped_frames.value} of {total_frames} "
              f"at a rate of {average_fps} fps. Video playback will approximately start in"
              f" {datetime.timedelta(seconds=(time_left-video_duration))}", end="")

    # todo: dynamically correct speed
    # this is currently just a band-aid fix over a bigger wound
    if sys.platform == "darwin":
        interval = (1 / (frame_rate*1.03))
    else:
        interval = (1 / (frame_rate*1.01))
    std_scr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    pygame.mixer.music.play()
    current_interval = interval
    global lag

    try:
        for current_frame in range(total_frames):
            if child_error.qsize() > 0:
                os.kill(os.getpid(), signal.SIGINT)
            start_time = datetime.datetime.now()
            terminal_lines = os.get_terminal_size().lines
            if frames.qsize() < 1:
                pygame.mixer.music.pause()
                std_scr.clear()
                std_scr.addstr(0, 0, "Buffering...")
                std_scr.refresh()
                time.sleep(10)
                std_scr.clear()
                pygame.mixer.music.unpause()
            frame_list = frames.get(timeout=interval)
            pre_duration = (datetime.datetime.now() - start_time).total_seconds()
            if pre_duration >= current_interval:
                lag += 1
                current_interval = (pre_duration - current_interval) / lag
            std_scr.refresh()
            h_line_idx = 0
            try:
                for frame in frame_list:
                    if frame[0] < terminal_lines - 1:
                        std_scr.addstr(frame[0], 0, frame[1])
                    h_line_idx += 1
            except _curses.error:
                continue
            duration = (datetime.datetime.now() - start_time).total_seconds()
            if duration < current_interval:
                time.sleep(current_interval - duration)
            else:
                lag += 1
                current_interval = (duration - current_interval) / lag
            if current_interval < interval:
                current_interval = interval
        os.kill(os.getpid(), signal.SIGINT)
    finally:
        curses.echo()
        curses.nocbreak()
        curses.endwin()
        if child_error.qsize() > 0:
            return child_error.get()


if __name__ == '__main__':
    print("ascii-video v1.0.0")
    if sys.platform not in ["linux", "darwin"]:
        print("\033[1;33mWarning\033[0m: This version of ascii-video has only been tested to on Unix based OSes such as"
              " Linux or MacOS. \nIf you are running this program in Windows, using cygwin is recommended. "
              "\nYou may also need to install the curses module manually."
              "\nThe behaviour of the program could be unpredictable.")
        input("Press enter to continue...")
    try:
        import curses
        import _curses
    except ModuleNotFoundError:
        curses = None
        _curses = None
        print(f"\033[1;31mError\033[0m: curses module not found. please make sure you have the package installed.")
        exit(1)
    if len(sys.argv) > 1:
        video_file = sys.argv[1]
    else:
        print("No video file specified. Please specify one. mp4 files works the best")
        video_file = None
        exit(1)

    video = cv2.VideoCapture(video_file)
    total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_rate = video.get(cv2.CAP_PROP_FPS)
    video_duration = (total_frames // frame_rate) + (total_frames % frame_rate) / frame_rate
    global_interval = (1 / frame_rate)
    manager = Manager()
    queue = manager.Queue()
    shared_dumped_frames = Value(ctypes.c_int, 0)
    shared_dumping_interval = Value(ctypes.c_float, 1)
    shared_child_error = manager.Queue()
    p1 = Process(target=dump_frames, args=(queue, shared_dumped_frames, shared_dumping_interval, shared_child_error,
                                           video_file, total_frames,),
                 name="Frame Dumper")
    try:
        p2 = Process(target=print_frames, args=(queue, shared_dumped_frames, shared_dumping_interval,
                                                shared_child_error))
        p1.exception = exception_handler
        p1.start()
        child_error_state = print_frames(queue, shared_dumped_frames, shared_dumping_interval, shared_child_error)
        if child_error_state:
            exception_handler(*child_error_state)
    finally:
        p1.terminate()

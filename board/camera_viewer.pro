QT += core gui widgets network
CONFIG += c++11
TARGET = camera_viewer_arm
SOURCES += main.cpp
!isEmpty(BOARD_NETWORK_LIBDIR): LIBS += -L$$BOARD_NETWORK_LIBDIR

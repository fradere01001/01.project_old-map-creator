
## Project 01 - 01.project_old-map-creator:
1. Core Idea & Architecture Rules:
What is the big picture?
a simple program for locating places in a text or xlsx file with coordinates, build them into a list and then show them all together.
an implementation for google maps would be great, maybe output the format needed for the personalised maps so that the maps themselves can be uploaded.

2. Active Backlog (To-Do):
- fix it -- done
- add import file -- done
- new xlsx extension -- done
- reworked error handling
- 
- formatter to work in tandem?
    - eg throw some file with some files and changes it in readable format
- picking up and adding on xlsx files
- don't ask for confirmation of a new one each entry
    - just add option to break cleanly with "finish" or similar
- building webui
- adding a map of the places with pins in the selected locations
    - on this one i think would be cool to have some googlemaps api to avoid havind to build the maps from the start and to make it implementable in a google maps account.

- test some cool walking algorithms, test what could be done with it
    - cool for applied knowledge and for implementing useful features

3. Known Bugs / Blockers:
- doesn't work 💀 -- now it does!
    - fixed local issue with package (openSSL didn't have a necessary certificate)

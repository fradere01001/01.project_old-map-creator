#!/usr/bin/python
# -*- coding: utf-8 -*-
# n1

import time
from geopy.geocoders import Nominatim
from xlwt import Workbook


def file():
    wb = Workbook()
    sheet1 = wb.add_sheet('Sheet 1')
    sheet1.write(0, 0, 'Info')
    sheet1.write(0, 1, 'Latitudine Longitudine')
    i = 1
    return wb,sheet1,i

wb, sheet1, i = file()
print('row number 1')

def cordinates(sheet1, i):
    
    while True:

        print('Pin on map')
        
        var_address = input('inserisci un posto: ')
        
            


        geolocator = Nominatim(user_agent="https://www.google.com/maps")
        location = geolocator.geocode(var_address)
    
        var_lat_long_1 = location.latitude, location.longitude
        var_lat_long= str(var_lat_long_1)
    

        sheet1.write( i, 0, location.address)
        sheet1.write( i, 1, var_lat_long)

        var_decision = input('do you want to continue? ')
        if var_decision == 'no':
            break
        else:
            i+=1
            print('\nrow number '+str(i))

try:
    cordinates(sheet1, i)
except AttributeError:
    ''' 
    #    devi aggiungere un posto valido, se vuoi uscire scrivi 'no' alla domanda
    #    il programma procederà a salvare il file   
    #    se non vuoi perdere progressi salva e crea dopo altro file
    '''

    time.sleep(2)
    var_name = input('How do you want to call the file? ')
    wb.save(var_name)

except KeyboardInterrupt:
    print(' --> the file won\'t be saved')
    time.sleep(2)





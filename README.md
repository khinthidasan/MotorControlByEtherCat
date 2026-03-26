Industrial Motor control by Python with Realtime Ethercat communication ( Motor + IO )

Language >> Python
communication >> EtherCat

$ pip install pysoem
https://pysoem.readthedocs.io/en/latest/installation.html

Ethercat Master >> motorControl.py
Slave 0 >> Fastech Ezi-SERVO II EtherCat Driver ( Slave 0 ) (EzS2-EC-42M-A) 
Slave 1 >>  Fasteach Ezi-IO ( slave 1 ) ( Ezi-IO-EC-I8O8N-T ) 

Sync motion with many motors ( asyncio task ) and IO control can be build easily by adding slave motor drivers.



